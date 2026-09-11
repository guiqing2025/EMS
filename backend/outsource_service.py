"""阶段6：委外执行链 — 委外单 → 发料 → 条码 → 送检 → 合格委托入库 / 不合格退货"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    ApPayableStub,
    ErpSupplier,
    OutsourceBarcode,
    OutsourceInspect,
    OutsourceInspectLine,
    OutsourceOrder,
    OutsourceOrderLine,
    OutsourcePlan,
    OutsourcePlanLine,
    OutsourceReceipt,
    OutsourceReceiptLine,
    OutsourceReturn,
    OutsourceReturnLine,
    OutsourceShipDoc,
    OutsourceShipLine,
    WarehouseMaterial,
)
from warehouse_service import record_inbound

WW_TRANSITIONS = {
    "draft": frozenset({"confirmed", "void"}),
    "confirmed": frozenset({"shipped", "partial", "closed", "void"}),
    "shipped": frozenset({"partial", "closed", "void"}),
    "partial": frozenset({"closed", "void"}),
    "closed": frozenset(),
    "void": frozenset(),
}


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _get_or_create_material(db: Session, *, stock_owner: str, material_code: str, material_name: str = "") -> WarehouseMaterial:
    owner = (stock_owner or "internal").strip() or "internal"
    code = (material_code or "").strip()
    if not code:
        raise ValueError("料号不能为空")
    row = (
        db.query(WarehouseMaterial)
        .filter(WarehouseMaterial.customer_id == owner, WarehouseMaterial.material_code == code)
        .first()
    )
    if row:
        return row
    row = WarehouseMaterial(
        customer_id=owner,
        customer_name="内部库存" if owner == "internal" else owner,
        material_code=code,
        material_name=material_name or code,
        qty=0,
        locked_qty=0,
    )
    db.add(row)
    db.flush()
    return row


def ww_line_to_dict(ln: OutsourceOrderLine) -> dict:
    return {
        "id": ln.id,
        "material_code": ln.material_code,
        "material_name": ln.material_name,
        "qty": ln.qty,
        "unit": ln.unit,
        "unit_price": ln.unit_price,
        "process": ln.process or "",
        "due_date": ln.due_date or "",
        "shipped_qty": ln.shipped_qty,
        "pass_qty": ln.pass_qty,
        "fail_qty": ln.fail_qty,
        "received_qty": ln.received_qty,
        "returned_qty": ln.returned_qty,
    }


def ww_to_dict(row: OutsourceOrder, lines: list[OutsourceOrderLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "ww_no": row.ww_no,
        "supplier_id": row.supplier_id,
        "supplier_name": row.supplier_name or "",
        "process": row.process or "",
        "source_plan_id": row.source_plan_id,
        "source_plan_no": row.source_plan_no or "",
        "stock_owner": row.stock_owner or "internal",
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [ww_line_to_dict(ln) for ln in lines]
    return d


def list_ww(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[OutsourceOrder]:
    query = db.query(OutsourceOrder)
    if status.strip():
        query = query.filter(OutsourceOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((OutsourceOrder.ww_no.like(like)) | (OutsourceOrder.supplier_name.like(like)))
    return query.order_by(OutsourceOrder.id.desc()).limit(limit).all()


def get_ww(db: Session, ww_id: int) -> tuple[OutsourceOrder, list[OutsourceOrderLine]]:
    row = db.query(OutsourceOrder).filter(OutsourceOrder.id == ww_id).first()
    if not row:
        raise ValueError("委外单不存在")
    lines = (
        db.query(OutsourceOrderLine)
        .filter(OutsourceOrderLine.ww_id == ww_id)
        .order_by(OutsourceOrderLine.sort_order, OutsourceOrderLine.id)
        .all()
    )
    return row, lines


def create_ww(db: Session, data: dict, *, user: str) -> OutsourceOrder:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("委外单至少一行")
    supplier_name = (data.get("supplier_name") or "").strip()
    supplier_id = data.get("supplier_id")
    if supplier_id and not supplier_name:
        s = db.query(ErpSupplier).filter(ErpSupplier.id == supplier_id).first()
        if s:
            supplier_name = s.name
    row = OutsourceOrder(
        ww_no=next_doc_number(db, "outsource_order"),
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        process=(data.get("process") or "").strip(),
        source_plan_id=data.get("source_plan_id"),
        source_plan_no=(data.get("source_plan_no") or "").strip(),
        stock_owner=(data.get("stock_owner") or "internal").strip() or "internal",
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for i, raw in enumerate(lines):
        db.add(
            OutsourceOrderLine(
                ww_id=row.id,
                sort_order=i,
                material_code=(raw.get("material_code") or "").strip(),
                material_name=(raw.get("material_name") or "").strip(),
                qty=float(raw.get("qty") or 0),
                unit=(raw.get("unit") or "PCS").strip() or "PCS",
                unit_price=float(raw.get("unit_price") or 0),
                process=(raw.get("process") or data.get("process") or "").strip(),
                due_date=(raw.get("due_date") or "").strip(),
            )
        )
    db.flush()
    return row


def set_ww_status(db: Session, ww_id: int, status: str, *, user: str = "") -> OutsourceOrder:
    row, lines = get_ww(db, ww_id)
    target = (status or "").strip()
    if target not in WW_TRANSITIONS.get(row.status, frozenset()):
        raise ValueError(f"委外单状态不可从 {row.status} → {target}")
    if target == "confirmed" and not lines:
        raise ValueError("无明细不可确认")
    row.status = target
    _touch(row)
    db.flush()
    return row


def create_ww_from_plan(
    db: Session, plan_id: int, *, supplier_name: str = "", supplier_id: Optional[int] = None, user: str
) -> OutsourceOrder:
    plan = db.query(OutsourcePlan).filter(OutsourcePlan.id == plan_id).first()
    if not plan:
        raise ValueError("委外计划不存在")
    if plan.status not in ("confirmed", "released"):
        raise ValueError("仅已确认/已下达的委外计划可下推")
    lines = (
        db.query(OutsourcePlanLine)
        .filter(OutsourcePlanLine.plan_id == plan_id)
        .order_by(OutsourcePlanLine.sort_order, OutsourcePlanLine.id)
        .all()
    )
    if not lines:
        raise ValueError("委外计划无明细")
    return create_ww(
        db,
        {
            "supplier_id": supplier_id,
            "supplier_name": supplier_name or "待指定委外厂",
            "source_plan_id": plan.id,
            "source_plan_no": plan.plan_no,
            "process": lines[0].process if lines else "",
            "remark": f"下推自委外计划 {plan.plan_no}",
            "lines": [
                {
                    "material_code": ln.material_code,
                    "material_name": ln.material_name,
                    "qty": ln.qty,
                    "unit": ln.unit,
                    "process": ln.process,
                    "due_date": ln.due_date,
                }
                for ln in lines
            ],
        },
        user=user,
    )


# —— 发料给委外 ——


def create_ship_from_ww(db: Session, ww_id: int, *, user: str) -> OutsourceShipDoc:
    ww, lines = get_ww(db, ww_id)
    if ww.status not in ("confirmed", "shipped", "partial"):
        raise ValueError("仅已确认委外单可发料")
    doc = OutsourceShipDoc(
        ship_no=next_doc_number(db, "outsource_ship"),
        ww_id=ww.id,
        ww_no=ww.ww_no,
        status="draft",
        created_by=user,
    )
    db.add(doc)
    db.flush()
    for ln in lines:
        pending = max(0.0, float(ln.qty or 0) - float(ln.shipped_qty or 0))
        if pending <= 0:
            continue
        db.add(
            OutsourceShipLine(
                ship_id=doc.id,
                ww_line_id=ln.id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=pending,
                unit=ln.unit,
            )
        )
    db.flush()
    if not db.query(OutsourceShipLine).filter(OutsourceShipLine.ship_id == doc.id).count():
        raise ValueError("无可发料数量")
    return doc


def confirm_ship(db: Session, ship_id: int, *, user: str) -> OutsourceShipDoc:
    doc = db.query(OutsourceShipDoc).filter(OutsourceShipDoc.id == ship_id).first()
    if not doc:
        raise ValueError("发料单不存在")
    if doc.status != "draft":
        raise ValueError(f"发料单状态 {doc.status} 不可确认")
    ww, _ = get_ww(db, doc.ww_id)
    lines = db.query(OutsourceShipLine).filter(OutsourceShipLine.ship_id == ship_id).all()
    for ln in lines:
        mat = _get_or_create_material(
            db, stock_owner=ww.stock_owner or "internal", material_code=ln.material_code, material_name=ln.material_name
        )
        qty = float(ln.qty or 0)
        avail = round(float(mat.qty or 0) - float(mat.locked_qty or 0), 4)
        if qty > avail:
            raise ValueError(f"{ln.material_code} 可用库存不足（可用 {avail}）")
        mat.qty = round(float(mat.qty or 0) - qty, 4)
        mat.updated_at = _now()
        if ln.ww_line_id:
            wln = db.query(OutsourceOrderLine).filter(OutsourceOrderLine.id == ln.ww_line_id).first()
            if wln:
                wln.shipped_qty = round(float(wln.shipped_qty or 0) + qty, 4)
    doc.status = "confirmed"
    doc.confirmed_at = _now()
    _touch(doc)
    if ww.status == "confirmed":
        ww.status = "shipped"
        _touch(ww)
    db.flush()
    return doc


def ship_to_dict(row: OutsourceShipDoc, lines: list[OutsourceShipLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "ship_no": row.ship_no,
        "ww_id": row.ww_id,
        "ww_no": row.ww_no,
        "status": row.status,
        "created_by": row.created_by,
        "confirmed_at": row.confirmed_at,
    }
    if lines is not None:
        d["lines"] = [
            {"id": ln.id, "material_code": ln.material_code, "material_name": ln.material_name, "qty": ln.qty}
            for ln in lines
        ]
    return d


def list_ships(db: Session, *, limit: int = 100) -> list[OutsourceShipDoc]:
    return db.query(OutsourceShipDoc).order_by(OutsourceShipDoc.id.desc()).limit(limit).all()


def get_ship(db: Session, sid: int) -> tuple[OutsourceShipDoc, list[OutsourceShipLine]]:
    row = db.query(OutsourceShipDoc).filter(OutsourceShipDoc.id == sid).first()
    if not row:
        raise ValueError("发料单不存在")
    lines = db.query(OutsourceShipLine).filter(OutsourceShipLine.ship_id == sid).all()
    return row, lines


# —— 条码 ——


def register_barcode(db: Session, data: dict, *, user: str) -> OutsourceBarcode:
    ww, _ = get_ww(db, int(data.get("ww_id") or 0))
    if ww.status not in ("confirmed", "shipped", "partial"):
        raise ValueError("委外单状态不可登记条码")
    code = (data.get("barcode") or "").strip()
    if not code:
        raise ValueError("条码不能为空")
    if db.query(OutsourceBarcode).filter(OutsourceBarcode.barcode == code).first():
        raise ValueError(f"条码已存在：{code}")
    row = OutsourceBarcode(
        ww_id=ww.id,
        barcode=code,
        material_code=(data.get("material_code") or "").strip(),
        qty=float(data.get("qty") or 1),
        scanned_by=user,
    )
    db.add(row)
    db.flush()
    return row


# —— 送检 ——


def create_inspect_from_ww(db: Session, ww_id: int, *, user: str) -> OutsourceInspect:
    ww, lines = get_ww(db, ww_id)
    if ww.status not in ("confirmed", "shipped", "partial"):
        raise ValueError("仅已确认/已发料委外单可送检")
    insp = OutsourceInspect(
        inspect_no=next_doc_number(db, "outsource_inspect"),
        ww_id=ww.id,
        ww_no=ww.ww_no,
        warehouse_code="INSPECT",
        status="draft",
        result="pending",
        created_by=user,
    )
    db.add(insp)
    db.flush()
    for ln in lines:
        pending = float(ln.shipped_qty or 0) or max(0.0, float(ln.qty or 0) - float(ln.pass_qty or 0) - float(ln.fail_qty or 0))
        if pending <= 0:
            continue
        db.add(
            OutsourceInspectLine(
                inspect_id=insp.id,
                ww_line_id=ln.id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=pending,
                unit=ln.unit,
            )
        )
    db.flush()
    if not db.query(OutsourceInspectLine).filter(OutsourceInspectLine.inspect_id == insp.id).count():
        raise ValueError("无可送检数量")
    return insp


def get_inspect(db: Session, iid: int) -> tuple[OutsourceInspect, list[OutsourceInspectLine]]:
    row = db.query(OutsourceInspect).filter(OutsourceInspect.id == iid).first()
    if not row:
        raise ValueError("送检单不存在")
    lines = db.query(OutsourceInspectLine).filter(OutsourceInspectLine.inspect_id == iid).all()
    return row, lines


def inspect_to_dict(row: OutsourceInspect, lines: list[OutsourceInspectLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "inspect_no": row.inspect_no,
        "ww_id": row.ww_id,
        "ww_no": row.ww_no,
        "status": row.status,
        "result": row.result,
        "judged_by": row.judged_by,
        "judged_at": row.judged_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "ww_line_id": ln.ww_line_id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "pass_qty": ln.pass_qty,
                "fail_qty": ln.fail_qty,
            }
            for ln in lines
        ]
    return d


def list_inspects(db: Session, *, limit: int = 100) -> list[OutsourceInspect]:
    return db.query(OutsourceInspect).order_by(OutsourceInspect.id.desc()).limit(limit).all()


def judge_inspect(db: Session, iid: int, judgments: list[dict], *, user: str) -> OutsourceInspect:
    insp, lines = get_inspect(db, iid)
    if insp.status != "draft":
        raise ValueError(f"送检单状态 {insp.status} 不可判定")
    by_id = {ln.id: ln for ln in lines}
    total_pass = total_fail = 0.0
    for j in judgments:
        ln = by_id.get(int(j.get("line_id") or 0))
        if not ln:
            raise ValueError("送检行不存在")
        p = float(j.get("pass_qty") or 0)
        f = float(j.get("fail_qty") or 0)
        if p < 0 or f < 0 or round(p + f, 4) > round(float(ln.qty or 0) + 1e-6, 4):
            raise ValueError(f"{ln.material_code} 判定数量非法")
        ln.pass_qty = p
        ln.fail_qty = f
        total_pass += p
        total_fail += f
        if ln.ww_line_id:
            wln = db.query(OutsourceOrderLine).filter(OutsourceOrderLine.id == ln.ww_line_id).first()
            if wln:
                wln.pass_qty = round(float(wln.pass_qty or 0) + p, 4)
                wln.fail_qty = round(float(wln.fail_qty or 0) + f, 4)
    if total_fail <= 0 and total_pass > 0:
        result = "pass"
    elif total_pass <= 0 and total_fail > 0:
        result = "fail"
    elif total_pass > 0 and total_fail > 0:
        result = "partial"
    else:
        raise ValueError("请填写合格或不合格数量")
    insp.status = "judged"
    insp.result = result
    insp.judged_by = user
    insp.judged_at = _now()
    _touch(insp)
    db.flush()
    return insp


# —— 委托入库 ——


def create_receipt_from_inspect(db: Session, inspect_id: int, *, user: str) -> OutsourceReceipt:
    insp, lines = get_inspect(db, inspect_id)
    if insp.status != "judged":
        raise ValueError("仅已判定送检可生成委托入库")
    pass_lines = [ln for ln in lines if float(ln.pass_qty or 0) > 0]
    if not pass_lines:
        raise ValueError("无合格数量，不可委托入库（请走退货）")
    ww, ww_lines = get_ww(db, insp.ww_id)
    price = {ln.id: float(ln.unit_price or 0) for ln in ww_lines}
    rec = OutsourceReceipt(
        receipt_no=next_doc_number(db, "outsource_receipt"),
        ww_id=ww.id,
        ww_no=ww.ww_no,
        inspect_id=insp.id,
        warehouse_code="GOOD",
        status="draft",
        created_by=user,
        remark=f"来源送检 {insp.inspect_no}",
    )
    db.add(rec)
    db.flush()
    for ln in pass_lines:
        db.add(
            OutsourceReceiptLine(
                receipt_id=rec.id,
                ww_line_id=ln.ww_line_id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=float(ln.pass_qty or 0),
                unit=ln.unit,
                unit_price=price.get(ln.ww_line_id or 0, 0),
            )
        )
    db.flush()
    return rec


def get_receipt(db: Session, rid: int) -> tuple[OutsourceReceipt, list[OutsourceReceiptLine]]:
    row = db.query(OutsourceReceipt).filter(OutsourceReceipt.id == rid).first()
    if not row:
        raise ValueError("委托入库单不存在")
    lines = db.query(OutsourceReceiptLine).filter(OutsourceReceiptLine.receipt_id == rid).all()
    return row, lines


def receipt_to_dict(row: OutsourceReceipt, lines: list[OutsourceReceiptLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "receipt_no": row.receipt_no,
        "ww_id": row.ww_id,
        "ww_no": row.ww_no,
        "inspect_id": row.inspect_id,
        "warehouse_code": row.warehouse_code,
        "status": row.status,
        "posted_by": row.posted_by,
        "posted_at": row.posted_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {"id": ln.id, "material_code": ln.material_code, "material_name": ln.material_name, "qty": ln.qty, "unit_price": ln.unit_price}
            for ln in lines
        ]
    return d


def list_receipts(db: Session, *, limit: int = 100) -> list[OutsourceReceipt]:
    return db.query(OutsourceReceipt).order_by(OutsourceReceipt.id.desc()).limit(limit).all()


def post_receipt(db: Session, rid: int, *, user: str) -> OutsourceReceipt:
    rec, lines = get_receipt(db, rid)
    if rec.status != "draft":
        raise ValueError(f"入库单状态 {rec.status} 不可过账")
    if (rec.warehouse_code or "").upper() != "GOOD":
        raise ValueError("委托入库仅允许 GOOD")
    if rec.inspect_id:
        insp, _ = get_inspect(db, rec.inspect_id)
        if insp.result == "fail":
            raise ValueError("送检不合格，禁止入良品仓")
    ww, ww_lines = get_ww(db, rec.ww_id)
    amount = 0.0
    for ln in lines:
        qty = float(ln.qty or 0)
        if qty <= 0:
            raise ValueError("入库数量须大于 0")
        mat = _get_or_create_material(
            db, stock_owner=ww.stock_owner or "internal", material_code=ln.material_code, material_name=ln.material_name
        )
        mat.qty = round(float(mat.qty or 0) + qty, 4)
        mat.updated_at = _now()
        record_inbound(db, mat, qty, "outsource", operator=user, remark=f"委托入库 {rec.receipt_no}", ref_no=rec.receipt_no)
        if ln.ww_line_id:
            wln = db.query(OutsourceOrderLine).filter(OutsourceOrderLine.id == ln.ww_line_id).first()
            if wln:
                wln.received_qty = round(float(wln.received_qty or 0) + qty, 4)
        amount += qty * float(ln.unit_price or 0)
    rec.status = "posted"
    rec.posted_by = user
    rec.posted_at = _now()
    _touch(rec)
    if all(float(ln.received_qty or 0) + float(ln.returned_qty or 0) >= float(ln.qty or 0) - 1e-6 for ln in ww_lines):
        if ww.status in ("confirmed", "shipped", "partial"):
            ww.status = "closed"
    else:
        if ww.status in ("confirmed", "shipped"):
            ww.status = "partial"
    _touch(ww)
    db.add(
        ApPayableStub(
            source_type="outsource_receipt",
            source_id=rec.id,
            source_no=rec.receipt_no,
            supplier_name=ww.supplier_name or "",
            amount=round(amount, 4),
            status="pending",
            remark="委外委托入库过账自动生成（阶段9正式启用）",
        )
    )
    db.flush()
    try:
        from gl_service import voucher_from_outsource_receipt

        voucher_from_outsource_receipt(
            db, receipt_id=rec.id, receipt_no=rec.receipt_no, amount=round(amount, 4), user=user
        )
    except Exception:
        pass
    return rec


# —— 退货 ——


def create_return_from_inspect(db: Session, inspect_id: int, *, user: str) -> OutsourceReturn:
    insp, lines = get_inspect(db, inspect_id)
    if insp.status != "judged":
        raise ValueError("仅已判定送检可生成退货")
    fail_lines = [ln for ln in lines if float(ln.fail_qty or 0) > 0]
    if not fail_lines:
        raise ValueError("无不合格数量")
    ww, _ = get_ww(db, insp.ww_id)
    ret = OutsourceReturn(
        return_no=next_doc_number(db, "outsource_return"),
        ww_id=ww.id,
        ww_no=ww.ww_no,
        inspect_id=insp.id,
        warehouse_code="RETURN",
        status="draft",
        created_by=user,
        remark=f"来源送检 {insp.inspect_no}",
    )
    db.add(ret)
    db.flush()
    for ln in fail_lines:
        db.add(
            OutsourceReturnLine(
                return_id=ret.id,
                ww_line_id=ln.ww_line_id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=float(ln.fail_qty or 0),
                unit=ln.unit,
            )
        )
    db.flush()
    return ret


def get_return(db: Session, rid: int) -> tuple[OutsourceReturn, list[OutsourceReturnLine]]:
    row = db.query(OutsourceReturn).filter(OutsourceReturn.id == rid).first()
    if not row:
        raise ValueError("退货单不存在")
    lines = db.query(OutsourceReturnLine).filter(OutsourceReturnLine.return_id == rid).all()
    return row, lines


def return_to_dict(row: OutsourceReturn, lines: list[OutsourceReturnLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "return_no": row.return_no,
        "ww_id": row.ww_id,
        "ww_no": row.ww_no,
        "inspect_id": row.inspect_id,
        "warehouse_code": row.warehouse_code,
        "status": row.status,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {"id": ln.id, "material_code": ln.material_code, "material_name": ln.material_name, "qty": ln.qty}
            for ln in lines
        ]
    return d


def list_returns(db: Session, *, limit: int = 100) -> list[OutsourceReturn]:
    return db.query(OutsourceReturn).order_by(OutsourceReturn.id.desc()).limit(limit).all()


def confirm_return(db: Session, rid: int, *, user: str = "") -> OutsourceReturn:
    ret, lines = get_return(db, rid)
    if ret.status != "draft":
        raise ValueError(f"退货单状态 {ret.status} 不可确认")
    if (ret.warehouse_code or "").upper() == "GOOD":
        raise ValueError("退货单不得写入 GOOD")
    for ln in lines:
        if ln.ww_line_id:
            wln = db.query(OutsourceOrderLine).filter(OutsourceOrderLine.id == ln.ww_line_id).first()
            if wln:
                wln.returned_qty = round(float(wln.returned_qty or 0) + float(ln.qty or 0), 4)
    ret.status = "confirmed"
    _touch(ret)
    ww, ww_lines = get_ww(db, ret.ww_id)
    if all(float(ln.received_qty or 0) + float(ln.returned_qty or 0) >= float(ln.qty or 0) - 1e-6 for ln in ww_lines):
        if ww.status in ("confirmed", "shipped", "partial"):
            ww.status = "closed"
            _touch(ww)
    db.flush()
    return ret
