"""阶段8：售后 — 投诉单、销售退货（补发/补货）、借样还入/转销售"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    ComplaintDoc,
    DeliveryNote,
    ErpSalesOrder,
    ErpSalesOrderLine,
    SalesIssue,
    SalesIssueLine,
    SalesReturn,
    SalesReturnLine,
    SampleLoan,
    WarehouseMaterial,
)
from warehouse_service import record_inbound


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _get_or_create_mat(db: Session, *, owner: str, code: str, name: str = "") -> WarehouseMaterial:
    owner = (owner or "internal").strip() or "internal"
    code = (code or "").strip()
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
        material_name=name or code,
        qty=0,
        locked_qty=0,
    )
    db.add(row)
    db.flush()
    return row


# —— 投诉单 ——


def complaint_to_dict(row: ComplaintDoc) -> dict:
    return {
        "id": row.id,
        "complaint_no": row.complaint_no,
        "so_id": row.so_id,
        "so_no": row.so_no or "",
        "delivery_id": row.delivery_id,
        "delivery_no": row.delivery_no or "",
        "customer_name": row.customer_name or "",
        "title": row.title or "",
        "content": row.content or "",
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
    }


def list_complaints(db: Session, *, q: str = "", limit: int = 100) -> list[ComplaintDoc]:
    query = db.query(ComplaintDoc)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (ComplaintDoc.complaint_no.like(like))
            | (ComplaintDoc.customer_name.like(like))
            | (ComplaintDoc.so_no.like(like))
            | (ComplaintDoc.title.like(like))
        )
    return query.order_by(ComplaintDoc.id.desc()).limit(limit).all()


def create_complaint(db: Session, data: dict, *, user: str) -> ComplaintDoc:
    so_id = data.get("so_id")
    delivery_id = data.get("delivery_id")
    so_no = (data.get("so_no") or "").strip()
    delivery_no = (data.get("delivery_no") or "").strip()
    customer_name = (data.get("customer_name") or "").strip()
    if so_id:
        so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
        if not so:
            raise ValueError("关联销售订单不存在")
        so_no = so.so_no
        customer_name = customer_name or so.customer_name or ""
    if delivery_id:
        dn = db.query(DeliveryNote).filter(DeliveryNote.id == delivery_id).first()
        if not dn:
            raise ValueError("关联发货单不存在")
        delivery_no = dn.delivery_no
        so_id = so_id or dn.so_id
        so_no = so_no or dn.so_no or ""
        customer_name = customer_name or dn.customer_name or ""
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("投诉标题必填")
    row = ComplaintDoc(
        complaint_no=next_doc_number(db, "complaint"),
        so_id=so_id,
        so_no=so_no,
        delivery_id=delivery_id,
        delivery_no=delivery_no,
        customer_name=customer_name,
        title=title,
        content=(data.get("content") or "").strip(),
        status=(data.get("status") or "open").strip() or "open",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def set_complaint_status(db: Session, cid: int, status: str, *, user: str = "") -> ComplaintDoc:
    row = db.query(ComplaintDoc).filter(ComplaintDoc.id == cid).first()
    if not row:
        raise ValueError("投诉单不存在")
    target = (status or "").strip()
    if target not in ("draft", "open", "closed", "void"):
        raise ValueError("非法状态")
    row.status = target
    _touch(row)
    db.flush()
    return row


# —— 销售退货 ——


def return_line_to_dict(ln: SalesReturnLine) -> dict:
    return {
        "id": ln.id,
        "so_line_id": ln.so_line_id,
        "material_code": ln.material_code,
        "material_name": ln.material_name,
        "qty": ln.qty,
        "unit": ln.unit,
        "unit_price": ln.unit_price,
    }


def return_to_dict(row: SalesReturn, lines: list[SalesReturnLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "return_no": row.return_no,
        "so_id": row.so_id,
        "so_no": row.so_no or "",
        "issue_id": row.issue_id,
        "issue_no": row.issue_no or "",
        "delivery_id": row.delivery_id,
        "delivery_no": row.delivery_no or "",
        "customer_name": row.customer_name or "",
        "stock_owner": row.stock_owner or "internal",
        "warehouse_code": row.warehouse_code or "RETURN",
        "status": row.status,
        "branch": row.branch or "none",
        "reissue_issue_id": row.reissue_issue_id,
        "reissue_delivery_id": row.reissue_delivery_id,
        "replenish_mo_id": row.replenish_mo_id,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "confirmed_at": row.confirmed_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [return_line_to_dict(ln) for ln in lines]
    return d


def list_returns(db: Session, *, limit: int = 100) -> list[SalesReturn]:
    return db.query(SalesReturn).order_by(SalesReturn.id.desc()).limit(limit).all()


def get_return(db: Session, rid: int) -> tuple[SalesReturn, list[SalesReturnLine]]:
    row = db.query(SalesReturn).filter(SalesReturn.id == rid).first()
    if not row:
        raise ValueError("销售退货单不存在")
    lines = db.query(SalesReturnLine).filter(SalesReturnLine.return_id == rid).all()
    return row, lines


def create_return_from_issue(db: Session, issue_id: int, *, user: str, qtys: list[dict] | None = None) -> SalesReturn:
    issue = db.query(SalesIssue).filter(SalesIssue.id == issue_id).first()
    if not issue:
        raise ValueError("销售出库单不存在")
    if issue.status not in ("posted", "delivered"):
        raise ValueError("仅已过账/已发货出库单可退货")
    lines = db.query(SalesIssueLine).filter(SalesIssueLine.issue_id == issue_id).all()
    qty_map = {int(x["issue_line_id"]): float(x["qty"]) for x in (qtys or []) if x.get("issue_line_id")}
    row = SalesReturn(
        return_no=next_doc_number(db, "sales_return"),
        so_id=issue.so_id,
        so_no=issue.so_no,
        issue_id=issue.id,
        issue_no=issue.issue_no,
        customer_name=issue.customer_name,
        stock_owner=issue.stock_owner or "internal",
        warehouse_code="RETURN",
        status="draft",
        created_by=user,
        remark=f"来源出库 {issue.issue_no}",
    )
    db.add(row)
    db.flush()
    for ln in lines:
        q = qty_map.get(ln.id, float(ln.qty or 0))
        if q <= 0:
            continue
        db.add(
            SalesReturnLine(
                return_id=row.id,
                so_line_id=ln.so_line_id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=q,
                unit=ln.unit,
                unit_price=ln.unit_price,
            )
        )
    db.flush()
    if not db.query(SalesReturnLine).filter(SalesReturnLine.return_id == row.id).count():
        raise ValueError("无退货行")
    return row


def create_return_from_delivery(db: Session, delivery_id: int, *, user: str) -> SalesReturn:
    dn = db.query(DeliveryNote).filter(DeliveryNote.id == delivery_id).first()
    if not dn:
        raise ValueError("发货单不存在")
    if dn.status != "confirmed":
        raise ValueError("仅已确认发货单可退货")
    row = create_return_from_issue(db, dn.issue_id, user=user)
    row.delivery_id = dn.id
    row.delivery_no = dn.delivery_no
    _touch(row)
    db.flush()
    return row


def confirm_return(db: Session, rid: int, *, user: str) -> SalesReturn:
    row, lines = get_return(db, rid)
    if row.status != "draft":
        raise ValueError(f"退货单状态 {row.status} 不可确认")
    for ln in lines:
        qty = float(ln.qty or 0)
        if qty <= 0:
            raise ValueError("退货数量须大于 0")
        mat = _get_or_create_mat(
            db, owner=row.stock_owner or "internal", code=ln.material_code, name=ln.material_name
        )
        mat.qty = round(float(mat.qty or 0) + qty, 4)
        mat.updated_at = _now()
        record_inbound(
            db,
            mat,
            qty,
            "customer_return",
            operator=user,
            remark=f"销售退货 {row.return_no}",
            ref_no=row.return_no,
        )
        if ln.so_line_id:
            sln = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.id == ln.so_line_id).first()
            if sln:
                sln.shipped_qty = max(0.0, round(float(sln.shipped_qty or 0) - qty, 4))
    row.status = "confirmed"
    row.confirmed_by = user
    row.confirmed_at = _now()
    _touch(row)
    if row.so_id:
        so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == row.so_id).first()
        if so and so.status in ("done", "closed", "partial_shipped"):
            so_lines = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.so_id == so.id).all()
            any_open = any(float(ln.shipped_qty or 0) + 1e-6 < float(ln.qty or 0) for ln in so_lines)
            if any_open:
                so.status = "partial_shipped" if any(float(ln.shipped_qty or 0) > 0 for ln in so_lines) else "executing"
                _touch(so)
    db.flush()
    return row


def branch_reissue(db: Session, rid: int, *, user: str, auto_deliver: bool = True) -> SalesReturn:
    """补发：按退货数量重新出库并可选生成发货单。"""
    from shipping_service import (
        confirm_delivery,
        create_delivery_from_issue,
        create_issue,
        post_issue,
    )

    row, lines = get_return(db, rid)
    if row.status != "confirmed":
        raise ValueError("仅已确认退货可补发")
    if row.branch == "reissue" and row.reissue_issue_id:
        raise ValueError("已补发，勿重复")
    if not row.so_id:
        raise ValueError("无关联销售订单，无法补发")
    issue = create_issue(
        db,
        {
            "so_id": row.so_id,
            "so_no": row.so_no,
            "customer_name": row.customer_name,
            "stock_owner": row.stock_owner or "internal",
            "remark": f"销退补发 ← {row.return_no}",
            "lines": [
                {
                    "so_line_id": ln.so_line_id,
                    "material_code": ln.material_code,
                    "material_name": ln.material_name,
                    "qty": ln.qty,
                    "unit": ln.unit,
                    "unit_price": ln.unit_price,
                }
                for ln in lines
            ],
        },
        user=user,
    )
    post_issue(db, issue.id, user=user)
    row.reissue_issue_id = issue.id
    row.branch = "reissue"
    if auto_deliver:
        deli = create_delivery_from_issue(db, issue.id, user=user, carrier="补发")
        confirm_delivery(db, deli.id, user=user)
        row.reissue_delivery_id = deli.id
    _touch(row)
    db.flush()
    return row


def branch_replenish(db: Session, rid: int, *, user: str) -> SalesReturn:
    """补货回生产：按退货行建生产单草稿。"""
    from production_service import create_mo

    row, lines = get_return(db, rid)
    if row.status != "confirmed":
        raise ValueError("仅已确认退货可补货生产")
    if row.branch == "replenish" and row.replenish_mo_id:
        raise ValueError("已补货，勿重复")
    ln0 = lines[0]
    mo = create_mo(
        db,
        {
            "material_code": ln0.material_code,
            "material_name": ln0.material_name,
            "qty": sum(float(ln.qty or 0) for ln in lines),
            "source_so_id": row.so_id,
            "source_so_no": row.so_no,
            "remark": f"销退补货 ← {row.return_no}",
        },
        user=user,
    )
    row.replenish_mo_id = mo.id
    row.branch = "replenish"
    _touch(row)
    db.flush()
    return row


# —— 借样还入 / 转销售 ——


def return_loan(db: Session, lid: int, *, user: str, restock: bool = True) -> SampleLoan:
    row = db.query(SampleLoan).filter(SampleLoan.id == lid).first()
    if not row:
        raise ValueError("借样单不存在")
    if row.status not in ("lent",):
        raise ValueError(f"借样状态 {row.status} 不可还入")
    row.status = "returned"
    row.returned_at = _now().strftime("%Y-%m-%d")
    _touch(row)
    if restock and row.product_code:
        mat = _get_or_create_mat(db, owner="internal", code=row.product_code, name=row.product_name)
        qty = float(row.qty or 1)
        mat.qty = round(float(mat.qty or 0) + qty, 4)
        mat.updated_at = _now()
        record_inbound(
            db, mat, qty, "customer_return", operator=user, remark=f"借样还入 {row.loan_no}", ref_no=row.loan_no
        )
    db.flush()
    return row


def convert_loan_to_so(db: Session, lid: int, *, user: str, unit_price: float = 0) -> ErpSalesOrder:
    from sales_service import create_sales_order

    row = db.query(SampleLoan).filter(SampleLoan.id == lid).first()
    if not row:
        raise ValueError("借样单不存在")
    if row.status not in ("lent", "returned"):
        raise ValueError(f"借样状态 {row.status} 不可转销售")
    if row.converted_so_id:
        raise ValueError("已转销售")
    so = create_sales_order(
        db,
        {
            "order_kind": "sample_convert",
            "customer_id": row.customer_id,
            "customer_name": row.customer_name,
            "remark": f"借样转销售 {row.loan_no}",
            "lines": [
                {
                    "material_code": row.product_code,
                    "material_name": row.product_name,
                    "qty": float(row.qty or 1),
                    "unit_price": unit_price,
                }
            ],
        },
        user=user,
    )
    row.status = "converted"
    row.converted_so_id = so.id
    if not row.returned_at:
        row.returned_at = _now().strftime("%Y-%m-%d")
    _touch(row)
    db.flush()
    return so
