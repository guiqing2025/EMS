"""阶段7：销售出货 — 销售出库 → 打包条码 → 发货单 → 回写 SO / 应收 stub"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    ArReceivableStub,
    DeliveryNote,
    DeliveryNoteLine,
    ErpSalesOrder,
    ErpSalesOrderLine,
    SalesIssue,
    SalesIssueBarcode,
    SalesIssueLine,
    WarehouseMaterial,
)
from warehouse_service import record_outbound

ISSUE_TRANSITIONS = {
    "draft": frozenset({"posted", "void"}),
    "posted": frozenset({"delivered", "void"}),
    "delivered": frozenset(),
    "void": frozenset(),
}

SHIPPABLE_SO = frozenset({"confirmed", "planning", "executing", "partial_shipped"})


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _get_material(db: Session, *, stock_owner: str, material_code: str, material_name: str = "") -> WarehouseMaterial:
    owner = (stock_owner or "internal").strip() or "internal"
    code = (material_code or "").strip()
    if not code:
        raise ValueError("料号不能为空")
    row = (
        db.query(WarehouseMaterial)
        .filter(WarehouseMaterial.customer_id == owner, WarehouseMaterial.material_code == code)
        .first()
    )
    if not row:
        raise ValueError(f"成品库存不存在：{code}（owner={owner}）")
    if material_name and not row.material_name:
        row.material_name = material_name
    return row


def issue_line_to_dict(ln: SalesIssueLine) -> dict:
    return {
        "id": ln.id,
        "so_line_id": ln.so_line_id,
        "material_code": ln.material_code,
        "material_name": ln.material_name,
        "qty": ln.qty,
        "unit": ln.unit,
        "unit_price": ln.unit_price,
        "packed_qty": ln.packed_qty,
    }


def issue_to_dict(row: SalesIssue, lines: list[SalesIssueLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "issue_no": row.issue_no,
        "so_id": row.so_id,
        "so_no": row.so_no or "",
        "customer_name": row.customer_name or "",
        "stock_owner": row.stock_owner or "internal",
        "warehouse_code": row.warehouse_code or "GOOD",
        "status": row.status,
        "source_fg_receipt_id": row.source_fg_receipt_id,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "posted_by": row.posted_by or "",
        "posted_at": row.posted_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [issue_line_to_dict(ln) for ln in lines]
    return d


def list_issues(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[SalesIssue]:
    query = db.query(SalesIssue)
    if status.strip():
        query = query.filter(SalesIssue.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter((SalesIssue.issue_no.like(like)) | (SalesIssue.so_no.like(like)) | (SalesIssue.customer_name.like(like)))
    return query.order_by(SalesIssue.id.desc()).limit(limit).all()


def get_issue(db: Session, issue_id: int) -> tuple[SalesIssue, list[SalesIssueLine]]:
    row = db.query(SalesIssue).filter(SalesIssue.id == issue_id).first()
    if not row:
        raise ValueError("销售出库单不存在")
    lines = (
        db.query(SalesIssueLine)
        .filter(SalesIssueLine.issue_id == issue_id)
        .order_by(SalesIssueLine.sort_order, SalesIssueLine.id)
        .all()
    )
    return row, lines


def create_issue(db: Session, data: dict, *, user: str) -> SalesIssue:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("出库单至少一行")
    row = SalesIssue(
        issue_no=next_doc_number(db, "sales_issue"),
        so_id=data.get("so_id"),
        so_no=(data.get("so_no") or "").strip(),
        customer_id=data.get("customer_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        stock_owner=(data.get("stock_owner") or "internal").strip() or "internal",
        warehouse_code=(data.get("warehouse_code") or "GOOD").strip() or "GOOD",
        status="draft",
        source_fg_receipt_id=data.get("source_fg_receipt_id"),
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for i, raw in enumerate(lines):
        db.add(
            SalesIssueLine(
                issue_id=row.id,
                so_line_id=raw.get("so_line_id"),
                sort_order=i,
                material_code=(raw.get("material_code") or "").strip(),
                material_name=(raw.get("material_name") or "").strip(),
                qty=float(raw.get("qty") or 0),
                unit=(raw.get("unit") or "PCS").strip() or "PCS",
                unit_price=float(raw.get("unit_price") or 0),
            )
        )
    db.flush()
    return row


def create_issue_from_so(db: Session, so_id: int, *, user: str, line_qtys: list[dict] | None = None) -> SalesIssue:
    so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
    if not so:
        raise ValueError("销售订单不存在")
    if so.status not in SHIPPABLE_SO:
        raise ValueError(f"销售订单状态 {so.status} 不可出库")
    so_lines = (
        db.query(ErpSalesOrderLine)
        .filter(ErpSalesOrderLine.so_id == so_id)
        .order_by(ErpSalesOrderLine.sort_order, ErpSalesOrderLine.id)
        .all()
    )
    if not so_lines:
        raise ValueError("销售订单无明细")
    qty_map = {int(x["so_line_id"]): float(x["qty"]) for x in (line_qtys or []) if x.get("so_line_id")}
    out_lines = []
    for ln in so_lines:
        pending = max(0.0, float(ln.qty or 0) - float(ln.shipped_qty or 0))
        if ln.id in qty_map:
            pending = min(pending, qty_map[ln.id])
        if pending <= 0:
            continue
        out_lines.append(
            {
                "so_line_id": ln.id,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "qty": pending,
                "unit": ln.unit,
                "unit_price": ln.unit_price,
            }
        )
    if not out_lines:
        raise ValueError("无可出库数量（已全部出货）")
    return create_issue(
        db,
        {
            "so_id": so.id,
            "so_no": so.so_no,
            "customer_id": so.customer_id,
            "customer_name": so.customer_name,
            "remark": f"下推自销售订单 {so.so_no}",
            "lines": out_lines,
        },
        user=user,
    )


def create_issue_from_fg(
    db: Session, fg_receipt_id: int, *, user: str, so_id: Optional[int] = None
) -> SalesIssue:
    """成品入库 direct_outbound：按 MO 关联销售单生成出库草稿。"""
    from models import FgReceipt, ProductionOrder

    fg = db.query(FgReceipt).filter(FgReceipt.id == fg_receipt_id).first()
    if not fg:
        raise ValueError("成品入库单不存在")
    if fg.status != "posted":
        raise ValueError("仅已过账成品入库可生成出库草稿")
    mo = db.query(ProductionOrder).filter(ProductionOrder.id == fg.mo_id).first()
    target_so = so_id or (mo.source_so_id if mo else None)
    if not target_so:
        # 无销售单时建孤立出库草稿
        return create_issue(
            db,
            {
                "so_no": (mo.source_so_no if mo else "") or "",
                "customer_name": "",
                "source_fg_receipt_id": fg.id,
                "remark": f"入库直接出库 ← {fg.receipt_no}",
                "lines": [
                    {
                        "material_code": fg.material_code,
                        "material_name": fg.material_name,
                        "qty": float(fg.qty or 0),
                        "unit": "PCS",
                        "unit_price": 0,
                    }
                ],
            },
            user=user,
        )
    so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == target_so).first()
    if not so:
        raise ValueError("关联销售订单不存在")
    so_lines = (
        db.query(ErpSalesOrderLine)
        .filter(ErpSalesOrderLine.so_id == so.id, ErpSalesOrderLine.material_code == fg.material_code)
        .all()
    )
    if not so_lines:
        so_lines = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.so_id == so.id).all()
    ln = so_lines[0] if so_lines else None
    qty = float(fg.qty or 0)
    if ln:
        pending = max(0.0, float(ln.qty or 0) - float(ln.shipped_qty or 0))
        qty = min(qty, pending) if pending > 0 else qty
    return create_issue(
        db,
        {
            "so_id": so.id,
            "so_no": so.so_no,
            "customer_id": so.customer_id,
            "customer_name": so.customer_name,
            "source_fg_receipt_id": fg.id,
            "remark": f"入库直接出库 ← {fg.receipt_no}",
            "lines": [
                {
                    "so_line_id": ln.id if ln else None,
                    "material_code": fg.material_code,
                    "material_name": fg.material_name,
                    "qty": qty,
                    "unit": (ln.unit if ln else "PCS"),
                    "unit_price": float(ln.unit_price or 0) if ln else 0,
                }
            ],
        },
        user=user,
    )


def _sync_so_after_ship(db: Session, so_id: int) -> None:
    so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
    if not so or so.status in ("void", "closed", "done"):
        return
    lines = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.so_id == so_id).all()
    if not lines:
        return
    all_done = all(float(ln.shipped_qty or 0) + 1e-6 >= float(ln.qty or 0) for ln in lines)
    any_shipped = any(float(ln.shipped_qty or 0) > 0 for ln in lines)
    # 推进到可出货态
    if so.status in ("confirmed", "planning"):
        so.status = "executing"
        _touch(so)
    if all_done:
        if so.status in ("executing", "partial_shipped"):
            so.status = "done"
            _touch(so)
    elif any_shipped:
        if so.status == "executing":
            so.status = "partial_shipped"
            _touch(so)
    db.flush()


def post_issue(db: Session, issue_id: int, *, user: str) -> SalesIssue:
    row, lines = get_issue(db, issue_id)
    if row.status != "draft":
        raise ValueError(f"出库单状态 {row.status} 不可过账")
    if (row.warehouse_code or "").upper() != "GOOD":
        raise ValueError("销售出库仅允许从 GOOD 扣减")
    if not lines:
        raise ValueError("无明细不可过账")
    for ln in lines:
        qty = float(ln.qty or 0)
        if qty <= 0:
            raise ValueError("出库数量须大于 0")
        mat = _get_material(
            db,
            stock_owner=row.stock_owner or "internal",
            material_code=ln.material_code,
            material_name=ln.material_name,
        )
        record_outbound(
            db,
            mat,
            qty,
            "sales",
            operator=user,
            remark=f"销售出库 {row.issue_no}",
            ref_no=row.issue_no,
        )
        if ln.so_line_id:
            sln = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.id == ln.so_line_id).first()
            if sln:
                new_shipped = round(float(sln.shipped_qty or 0) + qty, 4)
                if new_shipped > float(sln.qty or 0) + 1e-6:
                    raise ValueError(f"{sln.material_code} 出库后已发量超订单量")
                sln.shipped_qty = new_shipped
    row.status = "posted"
    row.posted_by = user
    row.posted_at = _now()
    _touch(row)
    if row.so_id:
        _sync_so_after_ship(db, row.so_id)
    db.flush()
    return row


def void_issue(db: Session, issue_id: int, *, user: str = "") -> SalesIssue:
    row, _ = get_issue(db, issue_id)
    if row.status != "draft":
        raise ValueError("仅草稿可作废")
    row.status = "void"
    _touch(row)
    db.flush()
    return row


# —— 打包条码 ——


def register_pack_barcode(db: Session, data: dict, *, user: str) -> SalesIssueBarcode:
    issue, lines = get_issue(db, int(data.get("issue_id") or 0))
    if issue.status not in ("draft", "posted"):
        raise ValueError("出库单状态不可登记打包条码")
    code = (data.get("barcode") or "").strip()
    if not code:
        raise ValueError("条码不能为空")
    if db.query(SalesIssueBarcode).filter(SalesIssueBarcode.barcode == code).first():
        raise ValueError(f"条码已存在：{code}")
    qty = float(data.get("qty") or 1)
    material_code = (data.get("material_code") or "").strip() or (lines[0].material_code if lines else "")
    row = SalesIssueBarcode(
        issue_id=issue.id,
        barcode=code,
        material_code=material_code,
        qty=qty,
        box_no=(data.get("box_no") or "").strip(),
        scanned_by=user,
    )
    db.add(row)
    if lines and material_code:
        for ln in lines:
            if ln.material_code == material_code:
                ln.packed_qty = round(float(ln.packed_qty or 0) + qty, 4)
                break
    db.flush()
    return row


def list_pack_barcodes(db: Session, issue_id: int) -> list[SalesIssueBarcode]:
    return (
        db.query(SalesIssueBarcode)
        .filter(SalesIssueBarcode.issue_id == issue_id)
        .order_by(SalesIssueBarcode.id.desc())
        .all()
    )


# —— 发货单 ——


def delivery_to_dict(row: DeliveryNote, lines: list[DeliveryNoteLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "delivery_no": row.delivery_no,
        "issue_id": row.issue_id,
        "issue_no": row.issue_no,
        "so_id": row.so_id,
        "so_no": row.so_no,
        "customer_name": row.customer_name,
        "status": row.status,
        "ship_date": row.ship_date,
        "carrier": row.carrier,
        "tracking_no": row.tracking_no,
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
                "unit_price": ln.unit_price,
            }
            for ln in lines
        ]
    return d


def list_deliveries(db: Session, *, limit: int = 100) -> list[DeliveryNote]:
    return db.query(DeliveryNote).order_by(DeliveryNote.id.desc()).limit(limit).all()


def get_delivery(db: Session, did: int) -> tuple[DeliveryNote, list[DeliveryNoteLine]]:
    row = db.query(DeliveryNote).filter(DeliveryNote.id == did).first()
    if not row:
        raise ValueError("发货单不存在")
    lines = db.query(DeliveryNoteLine).filter(DeliveryNoteLine.delivery_id == did).all()
    return row, lines


def create_delivery_from_issue(
    db: Session,
    issue_id: int,
    *,
    user: str,
    carrier: str = "",
    tracking_no: str = "",
    ship_date: str = "",
) -> DeliveryNote:
    issue, lines = get_issue(db, issue_id)
    if issue.status != "posted":
        raise ValueError("仅已过账出库单可生成发货单")
    existing = (
        db.query(DeliveryNote)
        .filter(DeliveryNote.issue_id == issue_id, DeliveryNote.status != "void")
        .first()
    )
    if existing:
        raise ValueError(f"该出库单已有发货单 {existing.delivery_no}")
    doc = DeliveryNote(
        delivery_no=next_doc_number(db, "delivery_note"),
        issue_id=issue.id,
        issue_no=issue.issue_no,
        so_id=issue.so_id,
        so_no=issue.so_no,
        customer_name=issue.customer_name,
        status="draft",
        ship_date=(ship_date or _now().strftime("%Y-%m-%d")),
        carrier=(carrier or "").strip(),
        tracking_no=(tracking_no or "").strip(),
        created_by=user,
        remark=f"来源出库 {issue.issue_no}",
    )
    db.add(doc)
    db.flush()
    for ln in lines:
        db.add(
            DeliveryNoteLine(
                delivery_id=doc.id,
                issue_line_id=ln.id,
                so_line_id=ln.so_line_id,
                material_code=ln.material_code,
                material_name=ln.material_name,
                qty=ln.qty,
                unit=ln.unit,
                unit_price=ln.unit_price,
            )
        )
    db.flush()
    return doc


def confirm_delivery(db: Session, delivery_id: int, *, user: str) -> DeliveryNote:
    doc, lines = get_delivery(db, delivery_id)
    if doc.status != "draft":
        raise ValueError(f"发货单状态 {doc.status} 不可确认")
    amount = sum(float(ln.qty or 0) * float(ln.unit_price or 0) for ln in lines)
    doc.status = "confirmed"
    doc.confirmed_by = user
    doc.confirmed_at = _now()
    _touch(doc)
    issue, _ = get_issue(db, doc.issue_id)
    if issue.status == "posted":
        issue.status = "delivered"
        _touch(issue)
    db.add(
        ArReceivableStub(
            source_type="delivery_note",
            source_id=doc.id,
            source_no=doc.delivery_no,
            customer_name=doc.customer_name or "",
            amount=round(amount, 4),
            status="pending",
            remark="发货确认自动生成（阶段9正式启用）",
        )
    )
    db.flush()
    try:
        from gl_service import voucher_from_delivery

        voucher_from_delivery(
            db, delivery_id=doc.id, delivery_no=doc.delivery_no, amount=round(amount, 4), user=user
        )
    except Exception:
        pass
    return doc


def delivery_print_payload(db: Session, delivery_id: int) -> dict:
    doc, lines = get_delivery(db, delivery_id)
    packs = list_pack_barcodes(db, doc.issue_id)
    return {
        **delivery_to_dict(doc, lines),
        "pack_barcodes": [
            {"barcode": p.barcode, "material_code": p.material_code, "qty": p.qty, "box_no": p.box_no}
            for p in packs
        ],
        "print_title": "发货单",
    }
