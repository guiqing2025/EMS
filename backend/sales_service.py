"""阶段2：销售订单 / 打样订单 / 备货单生命周期、BOM 绑定、旧 PO 导入"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    BomModel,
    ErpSalesOrder,
    ErpSalesOrderLine,
    ErpStockOrder,
    ErpStockOrderLine,
    SampleOrder,
    SrmOrder,
)

# 销售订单状态转移（白名单边）
SO_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"confirmed", "void"}),
    "confirmed": frozenset({"planning", "executing", "void"}),
    "planning": frozenset({"executing", "void"}),
    "executing": frozenset({"partial_shipped", "done", "closed"}),
    "partial_shipped": frozenset({"done", "closed", "executing"}),
    "done": frozenset({"closed", "partial_shipped", "executing"}),
    "closed": frozenset(),
    "void": frozenset(),
}

SAMPLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"confirmed", "void"}),
    "confirmed": frozenset({"in_progress", "void"}),
    "in_progress": frozenset({"done", "void"}),
    "done": frozenset(),
    "void": frozenset(),
}

STOCK_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"confirmed", "void"}),
    "confirmed": frozenset({"planning", "void"}),
    "planning": frozenset({"done", "closed", "void"}),
    "done": frozenset({"closed"}),
    "closed": frozenset(),
    "void": frozenset(),
}

EDITABLE_SO = frozenset({"draft"})
EDITABLE_SAMPLE = frozenset({"draft"})
EDITABLE_STOCK = frozenset({"draft"})


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _line_amount(qty: float, price: float) -> float:
    return round(float(qty or 0) * float(price or 0), 4)


def _get_bom(db: Session, bom_model_id: int) -> BomModel:
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom:
        raise ValueError("工程 BOM 不存在")
    if not bom.is_active:
        raise ValueError("工程 BOM 已停用")
    return bom


def _assert_transition(current: str, target: str, table: dict[str, frozenset[str]], label: str) -> None:
    allowed = table.get(current, frozenset())
    if target not in allowed:
        raise ValueError(f"{label}状态不可从 {current} → {target}")


# —— 销售订单 ——


def sales_line_to_dict(ln: ErpSalesOrderLine) -> dict:
    return {
        "id": ln.id,
        "sort_order": ln.sort_order,
        "material_code": ln.material_code,
        "material_name": ln.material_name,
        "spec": ln.spec,
        "qty": ln.qty,
        "unit": ln.unit,
        "unit_price": ln.unit_price,
        "amount": ln.amount,
        "due_date": ln.due_date or "",
        "shipped_qty": getattr(ln, "shipped_qty", 0) or 0,
        "bom_model_id": getattr(ln, "bom_model_id", None),
        "remark": ln.remark or "",
    }


def sales_order_to_dict(row: ErpSalesOrder, lines: list[ErpSalesOrderLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "so_no": row.so_no,
        "order_kind": row.order_kind,
        "inquiry_id": row.inquiry_id,
        "quote_id": row.quote_id,
        "sample_order_id": getattr(row, "sample_order_id", None),
        "customer_id": row.customer_id,
        "customer_name": row.customer_name or "",
        "external_po_no": getattr(row, "external_po_no", "") or "",
        "source_srm_line_key": getattr(row, "source_srm_line_key", "") or "",
        "require_bom": bool(getattr(row, "require_bom", False)),
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if lines is not None:
        d["lines"] = [sales_line_to_dict(ln) for ln in lines]
    return d


def list_sales_orders(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[ErpSalesOrder]:
    query = db.query(ErpSalesOrder)
    if status.strip():
        query = query.filter(ErpSalesOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                ErpSalesOrder.so_no.like(like),
                ErpSalesOrder.customer_name.like(like),
                ErpSalesOrder.external_po_no.like(like),
            )
        )
    return query.order_by(ErpSalesOrder.id.desc()).limit(limit).all()


def get_sales_order(db: Session, so_id: int) -> tuple[ErpSalesOrder, list[ErpSalesOrderLine]]:
    row = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
    if not row:
        raise ValueError("销售订单不存在")
    lines = (
        db.query(ErpSalesOrderLine)
        .filter(ErpSalesOrderLine.so_id == so_id)
        .order_by(ErpSalesOrderLine.sort_order, ErpSalesOrderLine.id)
        .all()
    )
    return row, lines


def _replace_so_lines(db: Session, so_id: int, lines_data: list[dict]) -> list[ErpSalesOrderLine]:
    db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.so_id == so_id).delete()
    out: list[ErpSalesOrderLine] = []
    for i, raw in enumerate(lines_data or []):
        qty = float(raw.get("qty") or 0)
        price = float(raw.get("unit_price") or 0)
        ln = ErpSalesOrderLine(
            so_id=so_id,
            sort_order=int(raw.get("sort_order") if raw.get("sort_order") is not None else i),
            material_code=(raw.get("material_code") or "").strip(),
            material_name=(raw.get("material_name") or "").strip(),
            spec=(raw.get("spec") or "").strip(),
            qty=qty,
            unit=(raw.get("unit") or "PCS").strip() or "PCS",
            unit_price=price,
            amount=_line_amount(qty, price),
            due_date=(raw.get("due_date") or "").strip(),
            shipped_qty=float(raw.get("shipped_qty") or 0),
            bom_model_id=raw.get("bom_model_id"),
            remark=(raw.get("remark") or "").strip(),
        )
        db.add(ln)
        out.append(ln)
    db.flush()
    return out


def create_sales_order(db: Session, data: dict, *, user: str) -> ErpSalesOrder:
    so = ErpSalesOrder(
        so_no=next_doc_number(db, "sales_order"),
        order_kind=(data.get("order_kind") or "sales").strip() or "sales",
        inquiry_id=data.get("inquiry_id"),
        quote_id=data.get("quote_id"),
        sample_order_id=data.get("sample_order_id"),
        customer_id=data.get("customer_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        external_po_no=(data.get("external_po_no") or "").strip(),
        source_srm_line_key=(data.get("source_srm_line_key") or "").strip(),
        require_bom=bool(data.get("require_bom") or False),
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(so)
    db.flush()
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("销售订单至少一行")
    _replace_so_lines(db, so.id, lines)
    return so


def update_sales_order(db: Session, so_id: int, data: dict, *, user: str) -> ErpSalesOrder:
    so, _ = get_sales_order(db, so_id)
    if so.status not in EDITABLE_SO:
        raise ValueError(f"仅草稿可编辑（当前 {so.status}）")
    for field in (
        "customer_id",
        "customer_name",
        "external_po_no",
        "remark",
        "require_bom",
        "order_kind",
    ):
        if field in data:
            val = data[field]
            if field in ("customer_name", "external_po_no", "remark", "order_kind") and val is not None:
                val = str(val).strip()
            if field == "require_bom":
                val = bool(val)
            setattr(so, field, val)
    if "lines" in data:
        if not data["lines"]:
            raise ValueError("销售订单至少一行")
        _replace_so_lines(db, so.id, data["lines"])
    _touch(so)
    db.flush()
    return so


def set_sales_order_status(db: Session, so_id: int, status: str, *, user: str = "") -> ErpSalesOrder:
    so, lines = get_sales_order(db, so_id)
    target = (status or "").strip()
    _assert_transition(so.status, target, SO_TRANSITIONS, "销售订单")
    if target == "confirmed" and not lines:
        raise ValueError("无明细行不可确认")
    if target == "planning" and so.require_bom:
        missing = [ln.material_code or ln.material_name or str(ln.id) for ln in lines if not ln.bom_model_id]
        if missing:
            raise ValueError(f"require_bom=是，以下行未绑定工程 BOM：{', '.join(missing)}")
    so.status = target
    _touch(so)
    db.flush()
    return so


def bind_sales_line_bom(db: Session, so_id: int, line_id: int, bom_model_id: Optional[int]) -> ErpSalesOrderLine:
    so, _ = get_sales_order(db, so_id)
    if so.status in ("void", "closed", "done"):
        raise ValueError(f"订单状态 {so.status} 不可绑定 BOM")
    ln = (
        db.query(ErpSalesOrderLine)
        .filter(ErpSalesOrderLine.id == line_id, ErpSalesOrderLine.so_id == so_id)
        .first()
    )
    if not ln:
        raise ValueError("订单行不存在")
    if bom_model_id is None:
        ln.bom_model_id = None
    else:
        _get_bom(db, int(bom_model_id))
        ln.bom_model_id = int(bom_model_id)
    _touch(so)
    db.flush()
    return ln


def create_sales_order_from_srm(db: Session, *, line_key: str = "", purchase_no: str = "", user: str) -> ErpSalesOrder:
    """旧客户 PO 导入为销售订单草稿（并存期工具）。"""
    q = db.query(SrmOrder)
    if line_key.strip():
        rows = q.filter(SrmOrder.line_key == line_key.strip()).all()
    elif purchase_no.strip():
        rows = q.filter(SrmOrder.purchase_no == purchase_no.strip()).order_by(SrmOrder.id).all()
    else:
        raise ValueError("请提供 line_key 或 purchase_no")
    if not rows:
        raise ValueError("未找到对应客户订单")
    first = rows[0]
    # 避免重复导入同一行
    if line_key.strip():
        existed = (
            db.query(ErpSalesOrder)
            .filter(ErpSalesOrder.source_srm_line_key == first.line_key)
            .first()
        )
        if existed:
            raise ValueError(f"该 PO 行已导入为 {existed.so_no}")
    so = ErpSalesOrder(
        so_no=next_doc_number(db, "sales_order"),
        order_kind="srm_import",
        customer_name=first.customer_name or "",
        external_po_no=first.purchase_no or "",
        source_srm_line_key=first.line_key if len(rows) == 1 else "",
        require_bom=False,
        status="draft",
        remark=f"导入自客户订单 {first.purchase_no}",
        created_by=user,
    )
    db.add(so)
    db.flush()
    for i, r in enumerate(rows):
        qty = float(r.batch_pur_qty or 0)
        price = float(r.tax_amount or 0)
        db.add(
            ErpSalesOrderLine(
                so_id=so.id,
                sort_order=i,
                material_code=r.product_goods_no or "",
                material_name=r.product_goods_name or "",
                spec=r.product_spec or "",
                qty=qty,
                unit="PCS",
                unit_price=price,
                amount=_line_amount(qty, price),
                due_date=(r.expect_arrival_date or "")[:16],
                bom_model_id=r.bom_model_id,
                remark=r.line_key or "",
            )
        )
    db.flush()
    return so


# —— 打样订单 ——


def sample_order_to_dict(row: SampleOrder) -> dict:
    return {
        "id": row.id,
        "sample_no": row.sample_no,
        "inquiry_id": row.inquiry_id,
        "quote_id": row.quote_id,
        "design_id": row.design_id,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name or "",
        "product_code": row.product_code or "",
        "product_name": row.product_name or "",
        "qty": row.qty,
        "unit": getattr(row, "unit", None) or "PCS",
        "unit_price": getattr(row, "unit_price", 0) or 0,
        "due_date": getattr(row, "due_date", "") or "",
        "sample_attr": getattr(row, "sample_attr", None) or "new_product",
        "bom_model_id": getattr(row, "bom_model_id", None),
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_sample_orders(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[SampleOrder]:
    query = db.query(SampleOrder)
    if status.strip():
        query = query.filter(SampleOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                SampleOrder.sample_no.like(like),
                SampleOrder.customer_name.like(like),
                SampleOrder.product_code.like(like),
            )
        )
    return query.order_by(SampleOrder.id.desc()).limit(limit).all()


def get_sample_order(db: Session, sid: int) -> SampleOrder:
    row = db.query(SampleOrder).filter(SampleOrder.id == sid).first()
    if not row:
        raise ValueError("打样订单不存在")
    return row


def update_sample_order(db: Session, sid: int, data: dict, *, user: str) -> SampleOrder:
    row = get_sample_order(db, sid)
    if row.status not in EDITABLE_SAMPLE:
        raise ValueError(f"仅草稿可编辑（当前 {row.status}）")
    for field in (
        "customer_id",
        "customer_name",
        "product_code",
        "product_name",
        "qty",
        "unit",
        "unit_price",
        "due_date",
        "sample_attr",
        "bom_model_id",
        "remark",
    ):
        if field not in data:
            continue
        val = data[field]
        if field in ("customer_name", "product_code", "product_name", "unit", "due_date", "sample_attr", "remark"):
            val = (val or "").strip() if val is not None else ""
        if field in ("qty", "unit_price"):
            val = float(val or 0)
        setattr(row, field, val)
    _touch(row)
    db.flush()
    return row


def set_sample_order_status(db: Session, sid: int, status: str, *, user: str = "") -> SampleOrder:
    row = get_sample_order(db, sid)
    target = (status or "").strip()
    _assert_transition(row.status, target, SAMPLE_TRANSITIONS, "打样订单")
    row.status = target
    _touch(row)
    db.flush()
    return row


def bind_sample_bom(db: Session, sid: int, bom_model_id: Optional[int]) -> SampleOrder:
    row = get_sample_order(db, sid)
    if row.status in ("void", "done"):
        raise ValueError(f"打样单状态 {row.status} 不可绑定 BOM")
    if bom_model_id is None:
        row.bom_model_id = None
    else:
        _get_bom(db, int(bom_model_id))
        row.bom_model_id = int(bom_model_id)
    _touch(row)
    db.flush()
    return row


def sample_to_sales_order(db: Session, sid: int, *, user: str) -> ErpSalesOrder:
    """打样完成（或确认后）转量产销售单。"""
    row = get_sample_order(db, sid)
    if row.status not in ("confirmed", "in_progress", "done"):
        raise ValueError("仅已确认/执行中/完成的打样单可转量产销售单")
    so = create_sales_order(
        db,
        {
            "order_kind": "sample_convert",
            "sample_order_id": row.id,
            "inquiry_id": row.inquiry_id,
            "quote_id": row.quote_id,
            "customer_id": row.customer_id,
            "customer_name": row.customer_name,
            "remark": f"打样转量产 {row.sample_no}",
            "lines": [
                {
                    "material_code": row.product_code,
                    "material_name": row.product_name,
                    "qty": row.qty or 1,
                    "unit": getattr(row, "unit", None) or "PCS",
                    "unit_price": getattr(row, "unit_price", 0) or 0,
                    "due_date": getattr(row, "due_date", "") or "",
                    "bom_model_id": getattr(row, "bom_model_id", None),
                }
            ],
        },
        user=user,
    )
    return so


# —— 备货单 ——


def stock_line_to_dict(ln: ErpStockOrderLine) -> dict:
    return {
        "id": ln.id,
        "sort_order": ln.sort_order,
        "material_code": ln.material_code,
        "material_name": ln.material_name,
        "qty": ln.qty,
        "unit": ln.unit,
        "due_date": ln.due_date or "",
        "bom_model_id": ln.bom_model_id,
        "remark": ln.remark or "",
    }


def stock_order_to_dict(row: ErpStockOrder, lines: list[ErpStockOrderLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "stock_no": row.stock_no,
        "stock_kind": row.stock_kind,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name or "",
        "warehouse_code": row.warehouse_code or "GOOD",
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if lines is not None:
        d["lines"] = [stock_line_to_dict(ln) for ln in lines]
    return d


def list_stock_orders(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[ErpStockOrder]:
    query = db.query(ErpStockOrder)
    if status.strip():
        query = query.filter(ErpStockOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(ErpStockOrder.stock_no.like(like), ErpStockOrder.customer_name.like(like))
        )
    return query.order_by(ErpStockOrder.id.desc()).limit(limit).all()


def get_stock_order(db: Session, sid: int) -> tuple[ErpStockOrder, list[ErpStockOrderLine]]:
    row = db.query(ErpStockOrder).filter(ErpStockOrder.id == sid).first()
    if not row:
        raise ValueError("备货单不存在")
    lines = (
        db.query(ErpStockOrderLine)
        .filter(ErpStockOrderLine.stock_id == sid)
        .order_by(ErpStockOrderLine.sort_order, ErpStockOrderLine.id)
        .all()
    )
    return row, lines


def _replace_stock_lines(db: Session, stock_id: int, lines_data: list[dict]) -> list[ErpStockOrderLine]:
    db.query(ErpStockOrderLine).filter(ErpStockOrderLine.stock_id == stock_id).delete()
    out: list[ErpStockOrderLine] = []
    for i, raw in enumerate(lines_data or []):
        ln = ErpStockOrderLine(
            stock_id=stock_id,
            sort_order=int(raw.get("sort_order") if raw.get("sort_order") is not None else i),
            material_code=(raw.get("material_code") or "").strip(),
            material_name=(raw.get("material_name") or "").strip(),
            qty=float(raw.get("qty") or 0),
            unit=(raw.get("unit") or "PCS").strip() or "PCS",
            due_date=(raw.get("due_date") or "").strip(),
            bom_model_id=raw.get("bom_model_id"),
            remark=(raw.get("remark") or "").strip(),
        )
        db.add(ln)
        out.append(ln)
    db.flush()
    return out


def create_stock_order(db: Session, data: dict, *, user: str) -> ErpStockOrder:
    lines = data.get("lines") or []
    if not lines:
        raise ValueError("备货单至少一行")
    kind = (data.get("stock_kind") or "internal").strip() or "internal"
    row = ErpStockOrder(
        stock_no=next_doc_number(db, "stock_order"),
        stock_kind=kind,
        customer_id=data.get("customer_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        warehouse_code=(data.get("warehouse_code") or "GOOD").strip() or "GOOD",
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    _replace_stock_lines(db, row.id, lines)
    return row


def update_stock_order(db: Session, sid: int, data: dict, *, user: str) -> ErpStockOrder:
    row, _ = get_stock_order(db, sid)
    if row.status not in EDITABLE_STOCK:
        raise ValueError(f"仅草稿可编辑（当前 {row.status}）")
    for field in ("stock_kind", "customer_id", "customer_name", "warehouse_code", "remark"):
        if field in data:
            val = data[field]
            if field in ("stock_kind", "customer_name", "warehouse_code", "remark") and val is not None:
                val = str(val).strip()
            setattr(row, field, val)
    if "lines" in data:
        if not data["lines"]:
            raise ValueError("备货单至少一行")
        _replace_stock_lines(db, row.id, data["lines"])
    _touch(row)
    db.flush()
    return row


def set_stock_order_status(db: Session, sid: int, status: str, *, user: str = "") -> ErpStockOrder:
    row, lines = get_stock_order(db, sid)
    target = (status or "").strip()
    _assert_transition(row.status, target, STOCK_TRANSITIONS, "备货单")
    if target == "confirmed" and not lines:
        raise ValueError("无明细行不可确认")
    row.status = target
    _touch(row)
    db.flush()
    return row
