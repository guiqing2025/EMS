"""销售 / 打样 / 备货 API（阶段2）"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from sales_service import (
    bind_sales_line_bom,
    bind_sample_bom,
    create_sales_order,
    create_sales_order_from_srm,
    create_stock_order,
    get_sales_order,
    get_sample_order,
    get_stock_order,
    list_sales_orders,
    list_sample_orders,
    list_stock_orders,
    sample_order_to_dict,
    sample_to_sales_order,
    sales_line_to_dict,
    sales_order_to_dict,
    set_sales_order_status,
    set_sample_order_status,
    set_stock_order_status,
    stock_order_to_dict,
    update_sales_order,
    update_sample_order,
    update_stock_order,
)
from flow_chain_service import get_flow_chain, push_flow_step
from doc_number import get_doc_number_rule, peek_doc_number, rule_to_dict, update_doc_number_rule
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/sales",
    tags=["sales"],
    dependencies=[Depends(require_system_auth)],
)

SALES_ROLES = frozenset({"admin", "sales", "pmc", "planner"})


def require_sales(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in SALES_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无销售模块权限")


class SoLineIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    spec: str = ""
    qty: float = 0
    unit: str = "PCS"
    unit_price: float = 0
    due_date: str = ""
    bom_model_id: Optional[int] = None
    remark: str = ""
    sort_order: Optional[int] = None


class SalesOrderIn(BaseModel):
    customer_id: Optional[int] = None
    customer_name: str = ""
    external_po_no: str = ""
    require_bom: bool = False
    order_kind: str = "sales"
    remark: str = ""
    lines: list[SoLineIn] = Field(default_factory=list)


class StatusIn(BaseModel):
    status: str


class BindBomIn(BaseModel):
    bom_model_id: Optional[int] = None


class FromSrmIn(BaseModel):
    line_key: str = ""
    purchase_no: str = ""


class OrderCodeIn(BaseModel):
    prefix: str = Field(..., min_length=1, max_length=16)
    name: str = "销售订单"
    date_fmt: str = "%Y%m%d"
    seq_width: int = Field(4, ge=3, le=8)


SALES_ORDER_DOC_TYPE = "sales_order"


@router.get("/order-code")
def get_sales_order_code(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_sales)):
    try:
        row = get_doc_number_rule(db, SALES_ORDER_DOC_TYPE)
        db.commit()
        data = rule_to_dict(row)
        data["preview_no"] = peek_doc_number(db, SALES_ORDER_DOC_TYPE)
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/order-code")
def update_sales_order_code(
    body: OrderCodeIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_sales),
):
    try:
        row = update_doc_number_rule(
            db,
            SALES_ORDER_DOC_TYPE,
            prefix=body.prefix,
            name=body.name,
            date_fmt=body.date_fmt,
            seq_width=body.seq_width,
        )
        db.commit()
        db.refresh(row)
        data = rule_to_dict(row)
        data["preview_no"] = peek_doc_number(db, SALES_ORDER_DOC_TYPE)
        return data
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/order-code/preview")
def preview_sales_order_code(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_sales)):
    try:
        no = peek_doc_number(db, SALES_ORDER_DOC_TYPE)
        db.commit()
        return {"doc_type": SALES_ORDER_DOC_TYPE, "doc_no": no}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class SampleOrderPatch(BaseModel):
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    due_date: Optional[str] = None
    sample_attr: Optional[str] = None
    bom_model_id: Optional[int] = None
    remark: Optional[str] = None


class StockLineIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"
    due_date: str = ""
    bom_model_id: Optional[int] = None
    remark: str = ""
    sort_order: Optional[int] = None


class StockOrderIn(BaseModel):
    stock_kind: str = "internal"
    customer_id: Optional[int] = None
    customer_name: str = ""
    warehouse_code: str = "GOOD"
    remark: str = ""
    lines: list[StockLineIn] = Field(default_factory=list)


def _dump(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=True)
    return model.dict(exclude_unset=True)  # type: ignore[attr-defined]


# —— 销售订单 ——


@router.get("/sales-orders")
def api_list_so(
    q: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_sales),
):
    items = []
    for r in list_sales_orders(db, q=q, status=status):
        _, lines = get_sales_order(db, r.id)
        items.append(sales_order_to_dict(r, lines))
    return {"items": items}


@router.post("/sales-orders")
def api_create_so(
    body: SalesOrderIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        so = create_sales_order(db, body.model_dump() if hasattr(body, "model_dump") else body.dict(), user=principal.username)
        db.commit()
        so, lines = get_sales_order(db, so.id)
        return sales_order_to_dict(so, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/sales-orders/{so_id}")
def api_get_so(so_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_sales)):
    try:
        so, lines = get_sales_order(db, so_id)
        return sales_order_to_dict(so, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/sales-orders/{so_id}")
def api_update_so(
    so_id: int, body: SalesOrderIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        update_sales_order(db, so_id, data, user=principal.username)
        db.commit()
        so, lines = get_sales_order(db, so_id)
        return sales_order_to_dict(so, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sales-orders/{so_id}/status")
def api_so_status(
    so_id: int, body: StatusIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        set_sales_order_status(db, so_id, body.status, user=principal.username)
        db.commit()
        so, lines = get_sales_order(db, so_id)
        return sales_order_to_dict(so, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sales-orders/{so_id}/lines/{line_id}/bind-bom")
def api_bind_so_bom(
    so_id: int,
    line_id: int,
    body: BindBomIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_sales),
):
    try:
        ln = bind_sales_line_bom(db, so_id, line_id, body.bom_model_id)
        db.commit()
        return sales_line_to_dict(ln)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/sales-orders/{so_id}/flow-chain")
def api_flow_chain(so_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_sales)):
    try:
        return get_flow_chain(db, so_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


class PushIn(BaseModel):
    plan_id: Optional[int] = None
    issue_id: Optional[int] = None
    delivery_id: Optional[int] = None
    supplier_name: str = ""


@router.post("/sales-orders/{so_id}/push/{step}")
def api_flow_push(
    so_id: int,
    step: str,
    body: PushIn = PushIn(),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_sales),
):
    try:
        out = push_flow_step(
            db,
            so_id,
            step,
            user=principal.username or "",
            plan_id=body.plan_id,
            issue_id=body.issue_id,
            delivery_id=body.delivery_id,
            supplier_name=body.supplier_name or "",
        )
        db.commit()
        return out
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sales-orders/from-srm")
def api_from_srm(
    body: FromSrmIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        so = create_sales_order_from_srm(
            db, line_key=body.line_key, purchase_no=body.purchase_no, user=principal.username
        )
        db.commit()
        so, lines = get_sales_order(db, so.id)
        return sales_order_to_dict(so, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


# —— 打样订单 ——


@router.get("/sample-orders")
def api_list_sample(
    q: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_sales),
):
    return {"items": [sample_order_to_dict(r) for r in list_sample_orders(db, q=q, status=status)]}


@router.get("/sample-orders/{sid}")
def api_get_sample(sid: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_sales)):
    try:
        return sample_order_to_dict(get_sample_order(db, sid))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/sample-orders/{sid}")
def api_update_sample(
    sid: int, body: SampleOrderPatch, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        row = update_sample_order(db, sid, _dump(body), user=principal.username)
        db.commit()
        return sample_order_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sample-orders/{sid}/status")
def api_sample_status(
    sid: int, body: StatusIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        row = set_sample_order_status(db, sid, body.status, user=principal.username)
        db.commit()
        return sample_order_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sample-orders/{sid}/bind-bom")
def api_sample_bind(
    sid: int, body: BindBomIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        row = bind_sample_bom(db, sid, body.bom_model_id)
        db.commit()
        return sample_order_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sample-orders/{sid}/to-sales-order")
def api_sample_to_so(
    sid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        so = sample_to_sales_order(db, sid, user=principal.username)
        db.commit()
        so, lines = get_sales_order(db, so.id)
        return sales_order_to_dict(so, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


# —— 备货单 ——


@router.get("/stock-orders")
def api_list_stock(
    q: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_sales),
):
    items = []
    for r in list_stock_orders(db, q=q, status=status):
        _, lines = get_stock_order(db, r.id)
        items.append(stock_order_to_dict(r, lines))
    return {"items": items}


@router.post("/stock-orders")
def api_create_stock(
    body: StockOrderIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        row = create_stock_order(db, data, user=principal.username)
        db.commit()
        row, lines = get_stock_order(db, row.id)
        return stock_order_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/stock-orders/{sid}")
def api_get_stock(sid: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_sales)):
    try:
        row, lines = get_stock_order(db, sid)
        return stock_order_to_dict(row, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/stock-orders/{sid}")
def api_update_stock(
    sid: int, body: StockOrderIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        update_stock_order(db, sid, data, user=principal.username)
        db.commit()
        row, lines = get_stock_order(db, sid)
        return stock_order_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/stock-orders/{sid}/status")
def api_stock_status(
    sid: int, body: StatusIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_sales)
):
    try:
        set_stock_order_status(db, sid, body.status, user=principal.username)
        db.commit()
        row, lines = get_stock_order(db, sid)
        return stock_order_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
