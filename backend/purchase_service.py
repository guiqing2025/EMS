"""阶段4：采购执行链 — 采购单 → 到货条码 → 送检 IQC → 合格入库 / 不合格退货"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    ApPayableStub,
    ErpSupplier,
    PurchaseArrivalBarcode,
    PurchaseInspect,
    PurchaseInspectLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    PurchaseReturn,
    PurchaseReturnLine,
    PurchasePlan,
    PurchasePlanLine,
    WarehouseMaterial,
)
from warehouse_service import record_inbound

PO_TRANSITIONS = {
    "draft": frozenset({"confirmed", "void"}),
    "confirmed": frozenset({"partial", "closed", "void"}),
    "partial": frozenset({"closed", "void"}),
    "closed": frozenset(),
    "void": frozenset(),
}


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _assert_po_status(current: str, target: str) -> None:
    if target not in PO_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"采购单状态不可从 {current} → {target}")


def _get_or_create_material(
    db: Session,
    *,
    stock_owner: str,
    material_code: str,
    material_name: str = "",
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
        if material_name and not row.material_name:
            row.material_name = material_name
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


# —— 采购单 ——


def po_line_to_dict(ln: PurchaseOrderLine) -> dict:
    return {
        "id": ln.id,
        "sort_order": ln.sort_order,
        "material_code": ln.material_code,
        "material_name": ln.material_name,
        "qty": ln.qty,
        "unit": ln.unit,
        "unit_price": ln.unit_price,
        "due_date": ln.due_date or "",
        "arrived_qty": ln.arrived_qty,
        "pass_qty": ln.pass_qty,
        "fail_qty": ln.fail_qty,
        "received_qty": ln.received_qty,
        "returned_qty": ln.returned_qty,
        "remark": ln.remark or "",
    }


def purchase_order_to_dict(row: PurchaseOrder, lines: list[PurchaseOrderLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "po_no": row.po_no,
        "supplier_id": row.supplier_id,
        "supplier_name": row.supplier_name or "",
        "source_plan_id": row.source_plan_id,
        "source_plan_no": row.source_plan_no or "",
        "stock_owner": row.stock_owner or "internal",
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if lines is not None:
        d["lines"] = [po_line_to_dict(ln) for ln in lines]
    return d


def list_purchase_orders(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[PurchaseOrder]:
    query = db.query(PurchaseOrder)
    if status.strip():
        query = query.filter(PurchaseOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (PurchaseOrder.po_no.like(like)) | (PurchaseOrder.supplier_name.like(like))
        )
    return query.order_by(PurchaseOrder.id.desc()).limit(limit).all()


def get_purchase_order(db: Session, po_id: int) -> tuple[PurchaseOrder, list[PurchaseOrderLine]]:
    row = db.query(PurchaseOrder).filter(PurchaseOrder.id == po_id).first()
    if not row:
        raise ValueError("采购单不存在")
    lines = (
        db.query(PurchaseOrderLine)
        .filter(PurchaseOrderLine.po_id == po_id)
        .order_by(PurchaseOrderLine.sort_order, PurchaseOrderLine.id)
        .all()
    )
    return row, lines


def _replace_po_lines(db: Session, po_id: int, lines_data: list[dict]) -> None:
    db.query(PurchaseOrderLine).filter(PurchaseOrderLine.po_id == po_id).delete()
    for i, raw in enumerate(lines_data or []):
        db.add(
            PurchaseOrderLine(
                po_id=po_id,
                sort_order=i,
                material_code=(raw.get("material_code") or "").strip(),
                material_name=(raw.get("material_name") or "").strip(),
                qty=float(raw.get("qty") or 0),
                unit=(raw.get("unit") or "PCS").strip() or "PCS",
                unit_price=float(raw.get("unit_price") or 0),
                due_date=(raw.get("due_date") or "").strip(),
                remark=(raw.get("remark") or "").strip(),
            )
        )
    db.flush()


def create_purchase_order(db: Session, data: dict, *, user: str) -> PurchaseOrder:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("采购单至少一行")
    supplier_name = (data.get("supplier_name") or "").strip()
    supplier_id = data.get("supplier_id")
    if supplier_id and not supplier_name:
        s = db.query(ErpSupplier).filter(ErpSupplier.id == supplier_id).first()
        if s:
            supplier_name = s.name
    row = PurchaseOrder(
        po_no=next_doc_number(db, "purchase_order"),
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        source_plan_id=data.get("source_plan_id"),
        source_plan_no=(data.get("source_plan_no") or "").strip(),
        stock_owner=(data.get("stock_owner") or "internal").strip() or "internal",
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    _replace_po_lines(db, row.id, lines)
    return row


def update_purchase_order(db: Session, po_id: int, data: dict, *, user: str = "") -> PurchaseOrder:
    row, _ = get_purchase_order(db, po_id)
    if row.status != "draft":
        raise ValueError(f"仅草稿可编辑（当前 {row.status}）")
    for field in ("supplier_id", "supplier_name", "stock_owner", "remark"):
        if field in data:
            val = data[field]
            if field in ("supplier_name", "stock_owner", "remark") and val is not None:
                val = str(val).strip()
            setattr(row, field, val)
    if "lines" in data:
        if not data["lines"]:
            raise ValueError("采购单至少一行")
        _replace_po_lines(db, row.id, data["lines"])
    _touch(row)
    db.flush()
    return row


def set_purchase_order_status(db: Session, po_id: int, status: str, *, user: str = "") -> PurchaseOrder:
    row, lines = get_purchase_order(db, po_id)
    target = (status or "").strip()
    _assert_po_status(row.status, target)
    if target == "confirmed" and not lines:
        raise ValueError("无明细不可确认")
    row.status = target
    _touch(row)
    db.flush()
    return row


def create_po_from_plan(
    db: Session, plan_id: int, *, supplier_name: str = "", supplier_id: Optional[int] = None, user: str
) -> PurchaseOrder:
    plan = db.query(PurchasePlan).filter(PurchasePlan.id == plan_id).first()
    if not plan:
        raise ValueError("采购计划不存在")
    if plan.status not in ("confirmed", "released"):
        raise ValueError("仅已确认/已下达的采购计划可下推")
    lines = (
        db.query(PurchasePlanLine)
        .filter(PurchasePlanLine.plan_id == plan_id)
        .order_by(PurchasePlanLine.sort_order, PurchasePlanLine.id)
        .all()
    )
    if not lines:
        raise ValueError("采购计划无明细")
    return create_purchase_order(
        db,
        {
            "supplier_id": supplier_id,
            "supplier_name": supplier_name or "待指定供应商",
            "source_plan_id": plan.id,
            "source_plan_no": plan.plan_no,
            "remark": f"下推自采购计划 {plan.plan_no}",
            "lines": [
                {
                    "material_code": ln.material_code,
                    "material_name": ln.material_name,
                    "qty": ln.qty,
                    "unit": ln.unit,
                    "due_date": ln.due_date,
                }
                for ln in lines
            ],
        },
        user=user,
    )


# —— 到货条码 ——


def register_arrival_barcode(db: Session, data: dict, *, user: str) -> PurchaseArrivalBarcode:
    po_id = int(data.get("po_id") or 0)
    po, lines = get_purchase_order(db, po_id)
    if po.status not in ("confirmed", "partial"):
        raise ValueError("仅已确认/部分收货的采购单可登记到货")
    barcode = (data.get("barcode") or "").strip()
    if not barcode:
        raise ValueError("条码不能为空")
    exists = db.query(PurchaseArrivalBarcode).filter(PurchaseArrivalBarcode.barcode == barcode).first()
    if exists:
        raise ValueError(f"条码已存在：{barcode}")
    po_line_id = data.get("po_line_id")
    material_code = (data.get("material_code") or "").strip()
    qty = float(data.get("qty") or 1)
    if po_line_id:
        ln = next((x for x in lines if x.id == int(po_line_id)), None)
        if not ln:
            raise ValueError("采购行不存在")
        material_code = material_code or ln.material_code
        ln.arrived_qty = round(float(ln.arrived_qty or 0) + qty, 4)
    elif material_code:
        ln = next((x for x in lines if x.material_code == material_code), None)
        if ln:
            po_line_id = ln.id
            ln.arrived_qty = round(float(ln.arrived_qty or 0) + qty, 4)
    row = PurchaseArrivalBarcode(
        po_id=po_id,
        po_line_id=int(po_line_id) if po_line_id else None,
        barcode=barcode,
        material_code=material_code,
        qty=qty,
        scanned_by=user,
        remark=(data.get("remark") or "").strip(),
    )
    db.add(row)
    _touch(po)
    db.flush()
    return row


def list_arrivals(db: Session, po_id: int) -> list[PurchaseArrivalBarcode]:
    return (
        db.query(PurchaseArrivalBarcode)
        .filter(PurchaseArrivalBarcode.po_id == po_id)
        .order_by(PurchaseArrivalBarcode.id.desc())
        .all()
    )


def arrival_to_dict(row: PurchaseArrivalBarcode) -> dict:
    return {
        "id": row.id,
        "po_id": row.po_id,
        "po_line_id": row.po_line_id,
        "barcode": row.barcode,
        "material_code": row.material_code,
        "qty": row.qty,
        "scanned_by": row.scanned_by,
        "scanned_at": row.scanned_at,
        "remark": row.remark,
    }


# —— 送检 / IQC ——


def create_inspect_from_po(db: Session, po_id: int, *, user: str, lines_override: list[dict] | None = None) -> PurchaseInspect:
    po, po_lines = get_purchase_order(db, po_id)
    if po.status not in ("confirmed", "partial"):
        raise ValueError("仅已确认/部分收货的采购单可送检")
    insp = PurchaseInspect(
        inspect_no=next_doc_number(db, "purchase_inspect"),
        po_id=po.id,
        po_no=po.po_no,
        warehouse_code="INSPECT",
        status="draft",
        result="pending",
        created_by=user,
    )
    db.add(insp)
    db.flush()
    if lines_override:
        for i, raw in enumerate(lines_override):
            db.add(
                PurchaseInspectLine(
                    inspect_id=insp.id,
                    po_line_id=raw.get("po_line_id"),
                    material_code=(raw.get("material_code") or "").strip(),
                    material_name=(raw.get("material_name") or "").strip(),
                    qty=float(raw.get("qty") or 0),
                    unit=(raw.get("unit") or "PCS").strip() or "PCS",
                )
            )
    else:
        for i, ln in enumerate(po_lines):
            # 待检量：到货量优先，否则整单数量 − 已检
            pending = float(ln.arrived_qty or 0) or max(0.0, float(ln.qty or 0) - float(ln.pass_qty or 0) - float(ln.fail_qty or 0))
            if pending <= 0:
                continue
            db.add(
                PurchaseInspectLine(
                    inspect_id=insp.id,
                    po_line_id=ln.id,
                    material_code=ln.material_code,
                    material_name=ln.material_name,
                    qty=pending,
                    unit=ln.unit,
                )
            )
    db.flush()
    lines = db.query(PurchaseInspectLine).filter(PurchaseInspectLine.inspect_id == insp.id).all()
    if not lines:
        raise ValueError("无可送检数量")
    return insp


def get_inspect(db: Session, iid: int) -> tuple[PurchaseInspect, list[PurchaseInspectLine]]:
    row = db.query(PurchaseInspect).filter(PurchaseInspect.id == iid).first()
    if not row:
        raise ValueError("送检单不存在")
    lines = (
        db.query(PurchaseInspectLine)
        .filter(PurchaseInspectLine.inspect_id == iid)
        .order_by(PurchaseInspectLine.id)
        .all()
    )
    return row, lines


def inspect_to_dict(row: PurchaseInspect, lines: list[PurchaseInspectLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "inspect_no": row.inspect_no,
        "po_id": row.po_id,
        "po_no": row.po_no,
        "warehouse_code": row.warehouse_code,
        "status": row.status,
        "result": row.result,
        "judged_by": row.judged_by,
        "judged_at": row.judged_at,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "po_line_id": ln.po_line_id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "pass_qty": ln.pass_qty,
                "fail_qty": ln.fail_qty,
                "unit": ln.unit,
                "remark": ln.remark,
            }
            for ln in lines
        ]
    return d


def list_inspects(db: Session, *, limit: int = 100) -> list[PurchaseInspect]:
    return db.query(PurchaseInspect).order_by(PurchaseInspect.id.desc()).limit(limit).all()


def judge_inspect(db: Session, iid: int, judgments: list[dict], *, user: str) -> PurchaseInspect:
    """IQC 判定。judgments: [{line_id, pass_qty, fail_qty}]"""
    insp, lines = get_inspect(db, iid)
    if insp.status != "draft":
        raise ValueError(f"送检单状态 {insp.status} 不可判定")
    by_id = {ln.id: ln for ln in lines}
    total_pass = 0.0
    total_fail = 0.0
    for j in judgments:
        ln = by_id.get(int(j.get("line_id") or 0))
        if not ln:
            raise ValueError("送检行不存在")
        pass_qty = float(j.get("pass_qty") or 0)
        fail_qty = float(j.get("fail_qty") or 0)
        if pass_qty < 0 or fail_qty < 0:
            raise ValueError("合格/不合格数量不能为负")
        if round(pass_qty + fail_qty, 4) > round(float(ln.qty or 0) + 1e-6, 4):
            raise ValueError(f"{ln.material_code} 判定数量超过送检量")
        ln.pass_qty = pass_qty
        ln.fail_qty = fail_qty
        total_pass += pass_qty
        total_fail += fail_qty
        if ln.po_line_id:
            po_ln = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.id == ln.po_line_id).first()
            if po_ln:
                po_ln.pass_qty = round(float(po_ln.pass_qty or 0) + pass_qty, 4)
                po_ln.fail_qty = round(float(po_ln.fail_qty or 0) + fail_qty, 4)

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


# —— 入库（仅合格）——


def create_receipt_from_inspect(db: Session, inspect_id: int, *, user: str) -> PurchaseReceipt:
    insp, lines = get_inspect(db, inspect_id)
    if insp.status != "judged":
        raise ValueError("仅已判定的送检单可生成入库单")
    pass_lines = [ln for ln in lines if float(ln.pass_qty or 0) > 0]
    if not pass_lines:
        raise ValueError("无合格数量，不可生成良品入库单（请走退货）")
    po, po_lines = get_purchase_order(db, insp.po_id)
    price_map = {ln.id: float(ln.unit_price or 0) for ln in po_lines}
    rec = PurchaseReceipt(
        receipt_no=next_doc_number(db, "purchase_receipt"),
        po_id=po.id,
        po_no=po.po_no,
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
            PurchaseReceiptLine(
                receipt_id=rec.id,
                po_line_id=ln.po_line_id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=float(ln.pass_qty or 0),
                unit=ln.unit,
                unit_price=price_map.get(ln.po_line_id or 0, 0),
            )
        )
    db.flush()
    return rec


def get_receipt(db: Session, rid: int) -> tuple[PurchaseReceipt, list[PurchaseReceiptLine]]:
    row = db.query(PurchaseReceipt).filter(PurchaseReceipt.id == rid).first()
    if not row:
        raise ValueError("入库单不存在")
    lines = (
        db.query(PurchaseReceiptLine)
        .filter(PurchaseReceiptLine.receipt_id == rid)
        .order_by(PurchaseReceiptLine.id)
        .all()
    )
    return row, lines


def receipt_to_dict(row: PurchaseReceipt, lines: list[PurchaseReceiptLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "receipt_no": row.receipt_no,
        "po_id": row.po_id,
        "po_no": row.po_no,
        "inspect_id": row.inspect_id,
        "warehouse_code": row.warehouse_code,
        "status": row.status,
        "posted_by": row.posted_by,
        "posted_at": row.posted_at,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "po_line_id": ln.po_line_id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
                "unit_price": ln.unit_price,
            }
            for ln in lines
        ]
    return d


def list_receipts(db: Session, *, limit: int = 100) -> list[PurchaseReceipt]:
    return db.query(PurchaseReceipt).order_by(PurchaseReceipt.id.desc()).limit(limit).all()


def post_receipt(db: Session, rid: int, *, user: str) -> PurchaseReceipt:
    """过账入良品仓：硬规则 — 仅 GOOD，且行数量必须来自合格判定链路。"""
    rec, lines = get_receipt(db, rid)
    if rec.status != "draft":
        raise ValueError(f"入库单状态 {rec.status} 不可过账")
    if (rec.warehouse_code or "").upper() != "GOOD":
        raise ValueError("采购入库仅允许写入 GOOD 良品仓")
    if not lines:
        raise ValueError("入库单无明细")
    # 若关联送检，再次校验不得含不合格量冒充入库
    if rec.inspect_id:
        insp, ilines = get_inspect(db, rec.inspect_id)
        if insp.result == "fail":
            raise ValueError("送检结果为不合格，禁止入良品仓")
        fail_codes = {ln.material_code for ln in ilines if float(ln.fail_qty or 0) > 0 and float(ln.pass_qty or 0) <= 0}
        for ln in lines:
            if ln.material_code in fail_codes:
                raise ValueError(f"{ln.material_code} 整行不合格，禁止入良品仓")

    po, _ = get_purchase_order(db, rec.po_id)
    amount = 0.0
    for ln in lines:
        qty = float(ln.qty or 0)
        if qty <= 0:
            raise ValueError("入库数量须大于 0")
        mat = _get_or_create_material(
            db,
            stock_owner=po.stock_owner or "internal",
            material_code=ln.material_code,
            material_name=ln.material_name,
        )
        mat.qty = round(float(mat.qty or 0) + qty, 4)
        mat.updated_at = _now()
        record_inbound(
            db,
            mat,
            qty,
            "purchase",
            operator=user,
            remark=f"采购入库 {rec.receipt_no}",
            ref_no=rec.receipt_no,
        )
        if ln.po_line_id:
            po_ln = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.id == ln.po_line_id).first()
            if po_ln:
                po_ln.received_qty = round(float(po_ln.received_qty or 0) + qty, 4)
        amount += qty * float(ln.unit_price or 0)

    rec.status = "posted"
    rec.posted_by = user
    rec.posted_at = _now()
    _touch(rec)

    # 更新采购单状态
    _, po_lines = get_purchase_order(db, po.id)
    if all(float(ln.received_qty or 0) + float(ln.returned_qty or 0) >= float(ln.qty or 0) - 1e-6 for ln in po_lines):
        if po.status in ("confirmed", "partial"):
            po.status = "closed"
    else:
        if po.status == "confirmed":
            po.status = "partial"
    _touch(po)

    # 应付挂钩点
    db.add(
        ApPayableStub(
            source_type="purchase_receipt",
            source_id=rec.id,
            source_no=rec.receipt_no,
            supplier_name=po.supplier_name or "",
            amount=round(amount, 4),
            status="pending",
            remark="采购入库过账自动生成（阶段9正式启用）",
        )
    )
    db.flush()
    try:
        from gl_service import voucher_from_purchase_receipt

        voucher_from_purchase_receipt(
            db, receipt_id=rec.id, receipt_no=rec.receipt_no, amount=round(amount, 4), user=user
        )
    except Exception:
        pass
    return rec


# —— 退货（不合格）——


def create_return_from_inspect(db: Session, inspect_id: int, *, user: str) -> PurchaseReturn:
    insp, lines = get_inspect(db, inspect_id)
    if insp.status != "judged":
        raise ValueError("仅已判定的送检单可生成退货单")
    fail_lines = [ln for ln in lines if float(ln.fail_qty or 0) > 0]
    if not fail_lines:
        raise ValueError("无不合格数量，无需退货")
    po, _ = get_purchase_order(db, insp.po_id)
    ret = PurchaseReturn(
        return_no=next_doc_number(db, "purchase_return"),
        po_id=po.id,
        po_no=po.po_no,
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
            PurchaseReturnLine(
                return_id=ret.id,
                po_line_id=ln.po_line_id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=float(ln.fail_qty or 0),
                unit=ln.unit,
            )
        )
    db.flush()
    return ret


def get_return(db: Session, rid: int) -> tuple[PurchaseReturn, list[PurchaseReturnLine]]:
    row = db.query(PurchaseReturn).filter(PurchaseReturn.id == rid).first()
    if not row:
        raise ValueError("退货单不存在")
    lines = (
        db.query(PurchaseReturnLine)
        .filter(PurchaseReturnLine.return_id == rid)
        .order_by(PurchaseReturnLine.id)
        .all()
    )
    return row, lines


def return_to_dict(row: PurchaseReturn, lines: list[PurchaseReturnLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "return_no": row.return_no,
        "po_id": row.po_id,
        "po_no": row.po_no,
        "inspect_id": row.inspect_id,
        "warehouse_code": row.warehouse_code,
        "status": row.status,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "po_line_id": ln.po_line_id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": ln.qty,
                "unit": ln.unit,
            }
            for ln in lines
        ]
    return d


def list_returns(db: Session, *, limit: int = 100) -> list[PurchaseReturn]:
    return db.query(PurchaseReturn).order_by(PurchaseReturn.id.desc()).limit(limit).all()


def confirm_return(db: Session, rid: int, *, user: str = "") -> PurchaseReturn:
    """确认退货：不合格不入 GOOD，只回写采购行 returned_qty。"""
    ret, lines = get_return(db, rid)
    if ret.status != "draft":
        raise ValueError(f"退货单状态 {ret.status} 不可确认")
    if (ret.warehouse_code or "").upper() == "GOOD":
        raise ValueError("退货单不得写入 GOOD 良品仓")
    for ln in lines:
        if ln.po_line_id:
            po_ln = db.query(PurchaseOrderLine).filter(PurchaseOrderLine.id == ln.po_line_id).first()
            if po_ln:
                po_ln.returned_qty = round(float(po_ln.returned_qty or 0) + float(ln.qty or 0), 4)
    ret.status = "confirmed"
    _touch(ret)
    po, po_lines = get_purchase_order(db, ret.po_id)
    if all(float(ln.received_qty or 0) + float(ln.returned_qty or 0) >= float(ln.qty or 0) - 1e-6 for ln in po_lines):
        if po.status in ("confirmed", "partial"):
            po.status = "closed"
            _touch(po)
    db.flush()
    return ret


def list_ap_stubs(db: Session, *, limit: int = 100) -> list[ApPayableStub]:
    return db.query(ApPayableStub).order_by(ApPayableStub.id.desc()).limit(limit).all()


def ap_stub_to_dict(row: ApPayableStub) -> dict:
    settled = float(getattr(row, "settled_amount", 0) or 0)
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_no": row.source_no,
        "supplier_name": row.supplier_name,
        "amount": row.amount,
        "settled_amount": settled,
        "open_amount": round(float(row.amount or 0) - settled, 4),
        "status": row.status,
        "remark": row.remark,
        "created_at": row.created_at,
    }
