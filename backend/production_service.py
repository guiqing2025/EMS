"""阶段5：生产执行链 — 生产单 → 领/补/退料 → QA → 成品入库"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    BomLine,
    ErpSalesOrder,
    FgReceipt,
    ProdMaterialDoc,
    ProdMaterialLine,
    ProductionBarcode,
    ProductionOrder,
    ProductionPlan,
    ProductionPlanLine,
    ProductionQa,
    WarehouseMaterial,
)
from warehouse_service import record_inbound

MO_TRANSITIONS = {
    "draft": frozenset({"released", "void"}),
    "released": frozenset({"issuing", "in_process", "void"}),
    "issuing": frozenset({"in_process", "qa", "void"}),
    "in_process": frozenset({"qa", "void"}),
    "qa": frozenset({"fg_done", "closed", "void"}),
    "fg_done": frozenset({"closed"}),
    "closed": frozenset(),
    "void": frozenset(),
}


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _assert_mo(cur: str, target: str) -> None:
    if target not in MO_TRANSITIONS.get(cur, frozenset()):
        raise ValueError(f"生产单状态不可从 {cur} → {target}")


def _get_or_create_material(
    db: Session, *, stock_owner: str, material_code: str, material_name: str = ""
) -> WarehouseMaterial:
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


def _available(mat: WarehouseMaterial) -> float:
    return round(float(mat.qty or 0) - float(mat.locked_qty or 0), 4)


# —— 生产单 ——


def mo_to_dict(row: ProductionOrder) -> dict:
    return {
        "id": row.id,
        "mo_no": row.mo_no,
        "source_plan_id": row.source_plan_id,
        "source_plan_no": row.source_plan_no or "",
        "source_so_id": row.source_so_id,
        "source_so_no": row.source_so_no or "",
        "bom_model_id": row.bom_model_id,
        "material_code": row.material_code,
        "material_name": row.material_name,
        "qty": row.qty,
        "unit": row.unit,
        "due_date": row.due_date or "",
        "stock_owner": row.stock_owner or "internal",
        "issued_sets": row.issued_sets,
        "qa_pass_qty": row.qa_pass_qty,
        "qa_fail_qty": row.qa_fail_qty,
        "fg_qty": row.fg_qty,
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_mos(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[ProductionOrder]:
    query = db.query(ProductionOrder)
    if status.strip():
        query = query.filter(ProductionOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (ProductionOrder.mo_no.like(like))
            | (ProductionOrder.material_code.like(like))
            | (ProductionOrder.source_so_no.like(like))
        )
    return query.order_by(ProductionOrder.id.desc()).limit(limit).all()


def get_mo(db: Session, mo_id: int) -> ProductionOrder:
    row = db.query(ProductionOrder).filter(ProductionOrder.id == mo_id).first()
    if not row:
        raise ValueError("生产单不存在")
    return row


def create_mo(db: Session, data: dict, *, user: str) -> ProductionOrder:
    code = (data.get("material_code") or "").strip()
    qty = float(data.get("qty") or 0)
    if not code or qty <= 0:
        raise ValueError("成品料号与数量必填")
    so_id = data.get("source_so_id")
    so_no = (data.get("source_so_no") or "").strip()
    if so_id and not so_no:
        so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
        if so:
            so_no = so.so_no
    row = ProductionOrder(
        mo_no=next_doc_number(db, "production_order"),
        source_plan_id=data.get("source_plan_id"),
        source_plan_no=(data.get("source_plan_no") or "").strip(),
        source_so_id=so_id,
        source_so_no=so_no,
        bom_model_id=data.get("bom_model_id"),
        material_code=code,
        material_name=(data.get("material_name") or "").strip(),
        qty=qty,
        unit=(data.get("unit") or "PCS").strip() or "PCS",
        due_date=(data.get("due_date") or "").strip(),
        stock_owner=(data.get("stock_owner") or "internal").strip() or "internal",
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def create_mo_from_plan(db: Session, plan_id: int, *, line_id: Optional[int] = None, user: str) -> list[ProductionOrder]:
    plan = db.query(ProductionPlan).filter(ProductionPlan.id == plan_id).first()
    if not plan:
        raise ValueError("生产计划不存在")
    if plan.status not in ("confirmed", "released"):
        raise ValueError("仅已确认/已下达的生产计划可下推")
    q = db.query(ProductionPlanLine).filter(ProductionPlanLine.plan_id == plan_id)
    if line_id:
        q = q.filter(ProductionPlanLine.id == line_id)
    lines = q.order_by(ProductionPlanLine.sort_order, ProductionPlanLine.id).all()
    if not lines:
        raise ValueError("生产计划无明细")
    out = []
    for ln in lines:
        so_no = ""
        if ln.source_so_id:
            so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == ln.source_so_id).first()
            so_no = so.so_no if so else ""
        out.append(
            create_mo(
                db,
                {
                    "source_plan_id": plan.id,
                    "source_plan_no": plan.plan_no,
                    "source_so_id": ln.source_so_id,
                    "source_so_no": so_no or ln.source_no,
                    "bom_model_id": ln.bom_model_id,
                    "material_code": ln.material_code,
                    "material_name": ln.material_name,
                    "qty": ln.qty,
                    "unit": ln.unit,
                    "due_date": ln.due_date,
                    "remark": f"下推自生产计划 {plan.plan_no}",
                },
                user=user,
            )
        )
    if plan.status == "confirmed":
        plan.status = "released"
        _touch(plan)
    db.flush()
    return out


def set_mo_status(db: Session, mo_id: int, status: str, *, user: str = "") -> ProductionOrder:
    row = get_mo(db, mo_id)
    target = (status or "").strip()
    _assert_mo(row.status, target)
    row.status = target
    _touch(row)
    db.flush()
    return row


# —— 条码 ——


def register_barcode(db: Session, mo_id: int, barcode: str, *, user: str, remark: str = "") -> ProductionBarcode:
    mo = get_mo(db, mo_id)
    if mo.status in ("void", "closed"):
        raise ValueError(f"生产单状态 {mo.status} 不可挂条码")
    code = (barcode or "").strip()
    if not code:
        raise ValueError("条码不能为空")
    if db.query(ProductionBarcode).filter(ProductionBarcode.barcode == code).first():
        raise ValueError(f"条码已存在：{code}")
    row = ProductionBarcode(
        mo_id=mo.id,
        barcode=code,
        source_so_id=mo.source_so_id,
        scanned_by=user,
        remark=remark or "",
    )
    db.add(row)
    if mo.status == "released":
        mo.status = "in_process"
        _touch(mo)
    db.flush()
    return row


def list_barcodes(db: Session, mo_id: int) -> list[ProductionBarcode]:
    return (
        db.query(ProductionBarcode)
        .filter(ProductionBarcode.mo_id == mo_id)
        .order_by(ProductionBarcode.id.desc())
        .all()
    )


def barcode_to_dict(row: ProductionBarcode) -> dict:
    return {
        "id": row.id,
        "mo_id": row.mo_id,
        "barcode": row.barcode,
        "source_so_id": row.source_so_id,
        "scanned_by": row.scanned_by,
        "scanned_at": row.scanned_at,
        "remark": row.remark,
    }


# —— 领/补/退料 ——


def _bom_issue_lines(db: Session, mo: ProductionOrder) -> list[dict]:
    if not mo.bom_model_id:
        raise ValueError("生产单未绑定 BOM，请手工填写领料行")
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == mo.bom_model_id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order, BomLine.id)
        .all()
    )
    if not lines:
        raise ValueError("BOM 无明细")
    out = []
    for ln in lines:
        out.append(
            {
                "material_code": ln.material_code or "",
                "material_name": ln.material_name or "",
                "qty": round(float(ln.qty_per or 0) * float(mo.qty or 0), 4),
                "unit": ln.unit or "PCS",
            }
        )
    return out


def material_doc_to_dict(row: ProdMaterialDoc, lines: list[ProdMaterialLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "doc_no": row.doc_no,
        "kind": row.kind,
        "mo_id": row.mo_id,
        "mo_no": row.mo_no,
        "status": row.status,
        "remark": row.remark,
        "created_by": row.created_by,
        "confirmed_by": row.confirmed_by,
        "confirmed_at": row.confirmed_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
                "remark": ln.remark,
            }
            for ln in lines
        ]
    return d


def get_material_doc(db: Session, doc_id: int) -> tuple[ProdMaterialDoc, list[ProdMaterialLine]]:
    row = db.query(ProdMaterialDoc).filter(ProdMaterialDoc.id == doc_id).first()
    if not row:
        raise ValueError("物料单据不存在")
    lines = (
        db.query(ProdMaterialLine)
        .filter(ProdMaterialLine.doc_id == doc_id)
        .order_by(ProdMaterialLine.id)
        .all()
    )
    return row, lines


def list_material_docs(db: Session, *, kind: str = "", mo_id: Optional[int] = None, limit: int = 100) -> list[ProdMaterialDoc]:
    q = db.query(ProdMaterialDoc)
    if kind.strip():
        q = q.filter(ProdMaterialDoc.kind == kind.strip())
    if mo_id:
        q = q.filter(ProdMaterialDoc.mo_id == mo_id)
    return q.order_by(ProdMaterialDoc.id.desc()).limit(limit).all()


def create_material_doc(
    db: Session,
    *,
    mo_id: int,
    kind: str,
    lines: list[dict] | None = None,
    from_bom: bool = False,
    user: str,
    remark: str = "",
) -> ProdMaterialDoc:
    mo = get_mo(db, mo_id)
    if mo.status in ("void", "closed", "draft"):
        raise ValueError("请先下达生产单后再领退料")
    k = (kind or "issue").strip()
    if k not in ("issue", "supplement", "return"):
        raise ValueError("kind 须为 issue/supplement/return")
    doc_type = {"issue": "material_issue", "supplement": "material_supplement", "return": "material_return"}[k]
    if from_bom and k in ("issue", "supplement"):
        lines = _bom_issue_lines(db, mo)
    if not lines:
        raise ValueError("物料单至少一行")
    doc = ProdMaterialDoc(
        doc_no=next_doc_number(db, doc_type),
        kind=k,
        mo_id=mo.id,
        mo_no=mo.mo_no,
        status="draft",
        remark=remark or "",
        created_by=user,
    )
    db.add(doc)
    db.flush()
    for raw in lines:
        qty = float(raw.get("qty") or 0)
        if qty <= 0:
            continue
        db.add(
            ProdMaterialLine(
                doc_id=doc.id,
                material_code=(raw.get("material_code") or "").strip(),
                material_name=(raw.get("material_name") or "").strip(),
                qty=qty,
                unit=(raw.get("unit") or "PCS").strip() or "PCS",
                remark=(raw.get("remark") or "").strip(),
            )
        )
    db.flush()
    lines2 = db.query(ProdMaterialLine).filter(ProdMaterialLine.doc_id == doc.id).all()
    if not lines2:
        raise ValueError("物料单无有效行")
    if mo.status == "released":
        mo.status = "issuing"
        _touch(mo)
    return doc


def confirm_material_doc(db: Session, doc_id: int, *, user: str) -> ProdMaterialDoc:
    doc, lines = get_material_doc(db, doc_id)
    if doc.status != "draft":
        raise ValueError(f"单据状态 {doc.status} 不可确认")
    mo = get_mo(db, doc.mo_id)
    owner = mo.stock_owner or "internal"
    for ln in lines:
        mat = _get_or_create_material(
            db, stock_owner=owner, material_code=ln.material_code, material_name=ln.material_name
        )
        qty = float(ln.qty or 0)
        if doc.kind in ("issue", "supplement"):
            avail = _available(mat)
            if qty > avail:
                raise ValueError(f"{ln.material_code} 可用库存不足（可用 {avail}）")
            mat.qty = round(float(mat.qty or 0) - qty, 4)
            mat.updated_at = _now()
        else:  # return
            mat.qty = round(float(mat.qty or 0) + qty, 4)
            mat.updated_at = _now()
            record_inbound(
                db,
                mat,
                qty,
                "return",
                operator=user,
                remark=f"生产退料 {doc.doc_no}",
                ref_no=doc.doc_no,
            )
    doc.status = "confirmed"
    doc.confirmed_by = user
    doc.confirmed_at = _now()
    _touch(doc)
    if doc.kind in ("issue", "supplement"):
        mo.issued_sets = round(float(mo.issued_sets or 0) + 1, 4)
        if mo.status in ("released", "issuing"):
            mo.status = "in_process"
        _touch(mo)
    db.flush()
    return doc


# —— QA ——


def qa_to_dict(row: ProductionQa) -> dict:
    return {
        "id": row.id,
        "qa_no": row.qa_no,
        "mo_id": row.mo_id,
        "mo_no": row.mo_no,
        "status": row.status,
        "result": row.result,
        "qty": row.qty,
        "pass_qty": row.pass_qty,
        "fail_qty": row.fail_qty,
        "judged_by": row.judged_by,
        "judged_at": row.judged_at,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def create_qa_from_mo(db: Session, mo_id: int, *, user: str, qty: Optional[float] = None) -> ProductionQa:
    mo = get_mo(db, mo_id)
    if mo.status not in ("in_process", "issuing", "qa"):
        raise ValueError("生产进行中才可建 QA 单")
    q = float(qty) if qty is not None else float(mo.qty or 0)
    if q <= 0:
        raise ValueError("检验数量须大于 0")
    row = ProductionQa(
        qa_no=next_doc_number(db, "production_qa"),
        mo_id=mo.id,
        mo_no=mo.mo_no,
        status="draft",
        result="pending",
        qty=q,
        created_by=user,
    )
    db.add(row)
    db.flush()
    if mo.status != "qa":
        mo.status = "qa"
        _touch(mo)
    db.flush()
    return row


def list_qas(db: Session, *, limit: int = 100) -> list[ProductionQa]:
    return db.query(ProductionQa).order_by(ProductionQa.id.desc()).limit(limit).all()


def get_qa(db: Session, qa_id: int) -> ProductionQa:
    row = db.query(ProductionQa).filter(ProductionQa.id == qa_id).first()
    if not row:
        raise ValueError("QA 单不存在")
    return row


def judge_qa(db: Session, qa_id: int, *, pass_qty: float, fail_qty: float, user: str) -> ProductionQa:
    row = get_qa(db, qa_id)
    if row.status != "draft":
        raise ValueError(f"QA 状态 {row.status} 不可判定")
    p = float(pass_qty or 0)
    f = float(fail_qty or 0)
    if p < 0 or f < 0:
        raise ValueError("数量不能为负")
    if round(p + f, 4) > round(float(row.qty or 0) + 1e-6, 4):
        raise ValueError("判定数量超过送检量")
    if p <= 0 and f <= 0:
        raise ValueError("请填写合格或不合格数量")
    row.pass_qty = p
    row.fail_qty = f
    if f <= 0 and p > 0:
        row.result = "pass"
    elif p <= 0 and f > 0:
        row.result = "fail"
    else:
        row.result = "partial"
    row.status = "judged"
    row.judged_by = user
    row.judged_at = _now()
    _touch(row)
    mo = get_mo(db, row.mo_id)
    mo.qa_pass_qty = round(float(mo.qa_pass_qty or 0) + p, 4)
    mo.qa_fail_qty = round(float(mo.qa_fail_qty or 0) + f, 4)
    _touch(mo)
    db.flush()
    return row


# —— 成品入库 ——


def fg_to_dict(row: FgReceipt) -> dict:
    return {
        "id": row.id,
        "receipt_no": row.receipt_no,
        "mo_id": row.mo_id,
        "mo_no": row.mo_no,
        "qa_id": row.qa_id,
        "material_code": row.material_code,
        "material_name": row.material_name,
        "qty": row.qty,
        "warehouse_code": row.warehouse_code,
        "direct_outbound": bool(row.direct_outbound),
        "status": row.status,
        "posted_by": row.posted_by,
        "posted_at": row.posted_at,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def create_fg_from_qa(
    db: Session, qa_id: int, *, user: str, direct_outbound: bool = False
) -> FgReceipt:
    qa = get_qa(db, qa_id)
    if qa.status != "judged":
        raise ValueError("仅已判定 QA 可生成成品入库")
    if float(qa.pass_qty or 0) <= 0:
        raise ValueError("无合格数量，禁止成品入库")
    mo = get_mo(db, qa.mo_id)
    row = FgReceipt(
        receipt_no=next_doc_number(db, "fg_receipt"),
        mo_id=mo.id,
        mo_no=mo.mo_no,
        qa_id=qa.id,
        material_code=mo.material_code,
        material_name=mo.material_name,
        qty=float(qa.pass_qty or 0),
        warehouse_code="GOOD",
        direct_outbound=bool(direct_outbound),
        status="draft",
        created_by=user,
        remark=f"来源 QA {qa.qa_no}" + ("；入库直接出库" if direct_outbound else ""),
    )
    db.add(row)
    db.flush()
    return row


def list_fg(db: Session, *, limit: int = 100) -> list[FgReceipt]:
    return db.query(FgReceipt).order_by(FgReceipt.id.desc()).limit(limit).all()


def get_fg(db: Session, rid: int) -> FgReceipt:
    row = db.query(FgReceipt).filter(FgReceipt.id == rid).first()
    if not row:
        raise ValueError("成品入库单不存在")
    return row


def post_fg(db: Session, rid: int, *, user: str) -> FgReceipt:
    row = get_fg(db, rid)
    if row.status != "draft":
        raise ValueError(f"入库单状态 {row.status} 不可过账")
    if (row.warehouse_code or "").upper() != "GOOD":
        raise ValueError("成品入库仅允许 GOOD")
    if row.qa_id:
        qa = get_qa(db, row.qa_id)
        if qa.result == "fail" or float(qa.pass_qty or 0) <= 0:
            raise ValueError("QA 不合格，禁止成品入库")
    mo = get_mo(db, row.mo_id)
    qty = float(row.qty or 0)
    if qty <= 0:
        raise ValueError("入库数量须大于 0")
    mat = _get_or_create_material(
        db,
        stock_owner=mo.stock_owner or "internal",
        material_code=row.material_code,
        material_name=row.material_name,
    )
    mat.qty = round(float(mat.qty or 0) + qty, 4)
    mat.updated_at = _now()
    record_inbound(
        db,
        mat,
        qty,
        "production",
        operator=user,
        remark=f"成品入库 {row.receipt_no}"
        + ("（待出库草稿标记）" if row.direct_outbound else ""),
        ref_no=row.receipt_no,
    )
    row.status = "posted"
    row.posted_by = user
    row.posted_at = _now()
    _touch(row)
    mo.fg_qty = round(float(mo.fg_qty or 0) + qty, 4)
    if float(mo.fg_qty or 0) + 1e-6 >= float(mo.qty or 0):
        mo.status = "fg_done"
    _touch(mo)
    if row.direct_outbound:
        from shipping_service import create_issue_from_fg

        try:
            create_issue_from_fg(db, row.id, user=user, so_id=mo.source_so_id)
        except ValueError:
            # 无库存/无可出数量时不阻断成品入库；草稿可后续手工补
            pass
    db.flush()
    return row


def pmc_mo_board(db: Session, *, limit: int = 50) -> list[dict]:
    rows = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.status.notin_(("void",)))
        .order_by(ProductionOrder.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "mo_no": r.mo_no,
            "material_code": r.material_code,
            "qty": r.qty,
            "status": r.status,
            "issued_sets": r.issued_sets,
            "qa_pass_qty": r.qa_pass_qty,
            "fg_qty": r.fg_qty,
            "source_so_no": r.source_so_no,
            "progress": f"{r.status} | 发料套数={r.issued_sets} QA合={r.qa_pass_qty} 入库={r.fg_qty}/{r.qty}",
        }
        for r in rows
    ]
