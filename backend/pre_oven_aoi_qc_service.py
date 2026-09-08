"""炉前 AOI 产线复判与品质改判（独立于产线扫码写入路径）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from board_gate import check_pre_oven_aoi_pass, is_fail, is_pass, pre_oven_aoi_for
from models import PreOvenAoiQcRecord
from pcba_barcode import parse_pcba_barcode
from pre_oven_aoi_sync import (
    format_pre_oven_fail_summary,
    pre_oven_fail_kind,
    pre_oven_fail_kind_label,
)
from quality_service import resolve_qc_confirm_operator

LINE_PASS_PREFIX = "manual:line_pass"
QC_PASS_PREFIX = "manual:qc_override"


def _norm_barcode(raw: str) -> str:
    code = (raw or "").strip().upper()
    parsed = parse_pcba_barcode(code)
    if parsed and parsed.get("barcode"):
        return str(parsed["barcode"]).strip().upper()
    return code


def _board_snapshot(row: Any) -> dict[str, Any]:
    return {
        "barcode": row.barcode,
        "result": row.result,
        "fail_summary": row.fail_summary,
        "machine": row.machine,
        "source_file": row.source_file,
        "tested_at": row.tested_at,
        "purchase_no": row.purchase_no,
        "model_code": row.model_code,
        "product_name": row.product_name,
        "side": row.side,
    }


def _qc_passed_barcodes(db: Session) -> set[str]:
    rows = (
        db.query(PreOvenAoiQcRecord.barcode)
        .filter(PreOvenAoiQcRecord.action == "qc_pass")
        .all()
    )
    return {str(r[0]).strip().upper() for r in rows if r and r[0]}


def _line_fail_barcodes(db: Session) -> set[str]:
    rows = (
        db.query(PreOvenAoiQcRecord.barcode)
        .filter(PreOvenAoiQcRecord.action == "line_fail")
        .all()
    )
    return {str(r[0]).strip().upper() for r in rows if r and r[0]}


def line_confirm(
    db: Session,
    *,
    barcode: str,
    action: str,
    operator: str,
    purchase_no: str = "",
    model_code: str = "",
    remark: str = "",
) -> dict[str, Any]:
    """后焊产线：炉前 AOI 真不良复判 PASS / 确认真不良 FALL。"""
    code = _norm_barcode(barcode)
    if not code:
        raise ValueError("请输入条码")
    act = (action or "").strip().lower()
    if act not in ("pass", "fail"):
        raise ValueError("action 须为 pass 或 fail")
    op = (operator or "").strip()
    if not op:
        raise ValueError("缺少操作员")

    row = pre_oven_aoi_for(db, code)
    if not row:
        raise ValueError("未找到该条码的炉前AOI记录")
    kind = pre_oven_fail_kind(result=row.result, fail_summary=row.fail_summary)
    if kind != "real_fail":
        raise ValueError("仅炉前AOI真不良需产线复判")
    if is_pass(row.result) and act == "pass":
        gate = check_pre_oven_aoi_pass(db, code)
        return {
            "status": "ok",
            "action": "pass",
            "barcode": code,
            "message": "已是 PASS，可继续后焊扫码",
            "gate_ok": bool(gate.get("ok")),
        }

    snap = _board_snapshot(row)
    now = datetime.utcnow()
    fail_reason = format_pre_oven_fail_summary(row.fail_summary)

    if act == "pass":
        prev_result = str(row.result or "")
        prev_source = row.source_file
        row.result = "PASS"
        row.source_file = f"{LINE_PASS_PREFIX}:{int(now.timestamp())}"
        row.synced_at = now
        audit = PreOvenAoiQcRecord(
            barcode=code,
            action="line_pass",
            prev_result=prev_result,
            fail_summary=row.fail_summary,
            prev_machine=row.machine,
            prev_source_file=prev_source,
            prev_tested_at=row.tested_at,
            purchase_no=(purchase_no or row.purchase_no or "").strip() or None,
            model_code=(model_code or row.model_code or "").strip() or None,
            reason=fail_reason or "产线复判PASS",
            remark=(remark or "").strip() or None,
            operator=op,
            operator_role="line_confirm",
            created_at=now,
        )
        db.add(audit)
        db.flush()
        gate = check_pre_oven_aoi_pass(db, code)
        return {
            "status": "ok",
            "action": "pass",
            "barcode": code,
            "message": "已复判 PASS，请重新扫码",
            "record_id": audit.id,
            "gate_ok": bool(gate.get("ok")),
            "fail_reason": fail_reason,
        }

    # act == fail
    if code in _line_fail_barcodes(db) and code not in _qc_passed_barcodes(db):
        return {
            "status": "ok",
            "action": "fail",
            "barcode": code,
            "message": "已确认真不良，请送维修",
            "fail_reason": fail_reason,
            "already_confirmed": True,
        }

    audit = PreOvenAoiQcRecord(
        barcode=code,
        action="line_fail",
        prev_result=str(row.result or "FAIL"),
        fail_summary=row.fail_summary,
        prev_machine=row.machine,
        prev_source_file=row.source_file,
        prev_tested_at=row.tested_at,
        purchase_no=(purchase_no or row.purchase_no or "").strip() or None,
        model_code=(model_code or row.model_code or "").strip() or None,
        reason=fail_reason or "产线确认真不良",
        remark=(remark or "").strip() or None,
        operator=op,
        operator_role="line_confirm",
        created_at=now,
    )
    db.add(audit)
    db.flush()
    return {
        "status": "ok",
        "action": "fail",
        "barcode": code,
        "message": "已确认真不良，请送维修；维修后由品质改判 PASS",
        "record_id": audit.id,
        "fail_reason": fail_reason,
    }


def override_to_pass(
    db: Session,
    *,
    barcode: str,
    confirm_password: str,
    submitted_by: str,
    reason: str,
    remark: str = "",
) -> dict[str, Any]:
    """品质：炉前 AOI 维修后改判 PASS。"""
    code = _norm_barcode(barcode)
    if not code:
        raise ValueError("请输入条码")
    reason_s = (reason or "").strip()
    if len(reason_s) < 2:
        raise ValueError("请填写改判原因")
    op = resolve_qc_confirm_operator(confirm_password)
    submitter = (submitted_by or "").strip()

    row = pre_oven_aoi_for(db, code)
    if not row:
        raise ValueError("未找到该条码的炉前AOI记录")
    if is_pass(row.result):
        raise ValueError("该板炉前AOI已是 PASS，无需改判")
    if not is_fail(row.result):
        raise ValueError(f"仅 FAIL/NG 可改判，当前结果为 {row.result or '空'}")
    kind = pre_oven_fail_kind(result=row.result, fail_summary=row.fail_summary)
    if kind != "real_fail":
        raise ValueError("仅炉前AOI真不良可品质改判")

    line_fails = _line_fail_barcodes(db)
    if code not in line_fails:
        raise ValueError("该板尚未产线确认真不良，不可改判")

    now = datetime.utcnow()
    prev_result = str(row.result or "")
    prev_source = row.source_file
    row.result = "PASS"
    row.source_file = f"{QC_PASS_PREFIX}:{int(now.timestamp())}"
    row.synced_at = now

    audit = PreOvenAoiQcRecord(
        barcode=code,
        action="qc_pass",
        prev_result=prev_result,
        fail_summary=row.fail_summary,
        prev_machine=row.machine,
        prev_source_file=prev_source,
        prev_tested_at=row.tested_at,
        purchase_no=row.purchase_no,
        model_code=row.model_code,
        reason=reason_s,
        remark=(remark or "").strip() or None,
        operator=op,
        operator_role=f"submit:{submitter}" if submitter else "qc_confirm",
        created_at=now,
    )
    db.add(audit)
    db.flush()
    gate = check_pre_oven_aoi_pass(db, code)
    return {
        "id": audit.id,
        "barcode": code,
        "previous_result": prev_result,
        "pre_oven_aoi_result": "PASS",
        "operator": op,
        "reason": reason_s,
        "gate_ok": bool(gate.get("ok")),
        "gate_message": gate.get("message") or "",
        "created_at": now.isoformat(sep=" ", timespec="seconds"),
    }


def list_pending_repairs(
    db: Session,
    *,
    keyword: str = "",
    purchase_no: str = "",
    model_code: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """列出产线已确认真不良、待维修改判的炉前 AOI 板。"""
    from models import PreOvenAoiBoardResult
    from sqlalchemy import func, or_

    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    kw = (keyword or "").strip().upper()
    pn = (purchase_no or "").strip()
    mc = (model_code or "").strip()

    qc_passed = _qc_passed_barcodes(db)
    line_fail = _line_fail_barcodes(db) - qc_passed
    if not line_fail:
        return {"total": 0, "items": []}

    result_u = func.upper(PreOvenAoiBoardResult.result)
    q = db.query(PreOvenAoiBoardResult).filter(
        PreOvenAoiBoardResult.barcode.in_(sorted(line_fail)),
        result_u.in_(("FAIL", "FALL", "NG")),
    )
    if kw:
        q = q.filter(PreOvenAoiBoardResult.barcode.like(f"%{kw}%"))
    if pn:
        q = q.filter(PreOvenAoiBoardResult.purchase_no.like(f"%{pn}%"))
    if mc:
        q = q.filter(
            or_(
                PreOvenAoiBoardResult.model_code.like(f"%{mc}%"),
                PreOvenAoiBoardResult.product_name.like(f"%{mc}%"),
            )
        )
    total = q.count()
    rows = (
        q.order_by(PreOvenAoiBoardResult.tested_at.desc(), PreOvenAoiBoardResult.id.desc())
        .offset(off)
        .limit(lim)
        .all()
    )
    items: list[dict[str, Any]] = []
    for r in rows:
        kind = pre_oven_fail_kind(result=r.result, fail_summary=r.fail_summary)
        items.append(
            {
                "barcode": r.barcode,
                "result": r.result,
                "fail_reason": format_pre_oven_fail_summary(r.fail_summary),
                "fail_kind": kind,
                "fail_kind_label": pre_oven_fail_kind_label(kind),
                "purchase_no": r.purchase_no,
                "model_code": r.model_code,
                "product_name": r.product_name,
                "side": r.side,
                "machine": r.machine,
                "tested_at": r.tested_at.isoformat(sep=" ", timespec="seconds")
                if r.tested_at
                else None,
                "source_file": r.source_file,
            }
        )
    return {"total": total, "items": items}


def list_qc_records(
    db: Session,
    *,
    barcode: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    lim = max(1, min(int(limit or 50), 200))
    off = max(0, int(offset or 0))
    code = _norm_barcode(barcode) if barcode else ""
    q = db.query(PreOvenAoiQcRecord).order_by(PreOvenAoiQcRecord.id.desc())
    if code:
        q = q.filter(PreOvenAoiQcRecord.barcode == code)
    total = q.count()
    rows = q.offset(off).limit(lim).all()
    items = [
        {
            "id": r.id,
            "barcode": r.barcode,
            "action": r.action,
            "prev_result": r.prev_result,
            "fail_reason": format_pre_oven_fail_summary(r.fail_summary),
            "reason": r.reason,
            "remark": r.remark,
            "operator": r.operator,
            "operator_role": r.operator_role,
            "purchase_no": r.purchase_no,
            "model_code": r.model_code,
            "created_at": r.created_at.isoformat(sep=" ", timespec="seconds")
            if r.created_at
            else None,
        }
        for r in rows
    ]
    return {"total": total, "items": items}
