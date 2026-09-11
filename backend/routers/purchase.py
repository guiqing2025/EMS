"""采购执行链 API"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from purchase_service import (
    ap_stub_to_dict,
    arrival_to_dict,
    confirm_return,
    create_inspect_from_po,
    create_po_from_plan,
    create_purchase_order,
    create_receipt_from_inspect,
    create_return_from_inspect,
    get_inspect,
    get_purchase_order,
    get_receipt,
    get_return,
    inspect_to_dict,
    judge_inspect,
    list_ap_stubs,
    list_arrivals,
    list_inspects,
    list_purchase_orders,
    list_receipts,
    list_returns,
    post_receipt,
    purchase_order_to_dict,
    receipt_to_dict,
    register_arrival_barcode,
    return_to_dict,
    set_purchase_order_status,
    update_purchase_order,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/purchase",
    tags=["purchase"],
    dependencies=[Depends(require_system_auth)],
)

BUY_ROLES = frozenset({"admin", "purchasing", "pmc", "planner", "quality", "warehouse"})


def require_buy(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in BUY_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无采购模块权限")


class PoLineIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"
    unit_price: float = 0
    due_date: str = ""
    remark: str = ""


class PurchaseOrderIn(BaseModel):
    supplier_id: Optional[int] = None
    supplier_name: str = ""
    stock_owner: str = "internal"
    remark: str = ""
    lines: list[PoLineIn] = Field(default_factory=list)


class StatusIn(BaseModel):
    status: str


class FromPlanIn(BaseModel):
    supplier_id: Optional[int] = None
    supplier_name: str = ""


class ArrivalIn(BaseModel):
    po_id: int
    po_line_id: Optional[int] = None
    barcode: str
    material_code: str = ""
    qty: float = 1
    remark: str = ""


class JudgeLineIn(BaseModel):
    line_id: int
    pass_qty: float = 0
    fail_qty: float = 0


class JudgeIn(BaseModel):
    lines: list[JudgeLineIn] = Field(default_factory=list)


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.get("/orders")
def api_list_po(
    q: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_buy),
):
    items = []
    for r in list_purchase_orders(db, q=q, status=status):
        _, lines = get_purchase_order(db, r.id)
        items.append(purchase_order_to_dict(r, lines))
    return {"items": items}


@router.post("/orders")
def api_create_po(
    body: PurchaseOrderIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        row = create_purchase_order(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_purchase_order(db, row.id)
        return purchase_order_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/orders/{po_id}")
def api_get_po(po_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_buy)):
    try:
        row, lines = get_purchase_order(db, po_id)
        return purchase_order_to_dict(row, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/orders/{po_id}")
def api_update_po(
    po_id: int, body: PurchaseOrderIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        update_purchase_order(db, po_id, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_purchase_order(db, po_id)
        return purchase_order_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/orders/{po_id}/status")
def api_po_status(
    po_id: int, body: StatusIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        set_purchase_order_status(db, po_id, body.status, user=principal.username)
        db.commit()
        row, lines = get_purchase_order(db, po_id)
        return purchase_order_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/orders/from-plan/{plan_id}")
def api_from_plan(
    plan_id: int, body: FromPlanIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        row = create_po_from_plan(
            db, plan_id, supplier_name=body.supplier_name, supplier_id=body.supplier_id, user=principal.username
        )
        db.commit()
        row, lines = get_purchase_order(db, row.id)
        return purchase_order_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/arrivals")
def api_arrival(body: ArrivalIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)):
    try:
        row = register_arrival_barcode(db, _dump(body), user=principal.username)
        db.commit()
        return arrival_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/orders/{po_id}/arrivals")
def api_list_arrival(po_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_buy)):
    return {"items": [arrival_to_dict(r) for r in list_arrivals(db, po_id)]}


@router.post("/inspects/from-po/{po_id}")
def api_create_inspect(
    po_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        row = create_inspect_from_po(db, po_id, user=principal.username)
        db.commit()
        row, lines = get_inspect(db, row.id)
        return inspect_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/inspects")
def api_list_inspect(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_buy)):
    items = []
    for r in list_inspects(db):
        _, lines = get_inspect(db, r.id)
        items.append(inspect_to_dict(r, lines))
    return {"items": items}


@router.get("/inspects/{iid}")
def api_get_inspect(iid: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_buy)):
    try:
        row, lines = get_inspect(db, iid)
        return inspect_to_dict(row, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/inspects/{iid}/judge")
def api_judge(
    iid: int, body: JudgeIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        judge_inspect(db, iid, [x.model_dump() if hasattr(x, "model_dump") else x.dict() for x in body.lines], user=principal.username)
        db.commit()
        row, lines = get_inspect(db, iid)
        return inspect_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/receipts/from-inspect/{inspect_id}")
def api_create_receipt(
    inspect_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        row = create_receipt_from_inspect(db, inspect_id, user=principal.username)
        db.commit()
        row, lines = get_receipt(db, row.id)
        return receipt_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/receipts")
def api_list_receipt(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_buy)):
    items = []
    for r in list_receipts(db):
        _, lines = get_receipt(db, r.id)
        items.append(receipt_to_dict(r, lines))
    return {"items": items}


@router.post("/receipts/{rid}/post")
def api_post_receipt(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)):
    try:
        post_receipt(db, rid, user=principal.username)
        db.commit()
        row, lines = get_receipt(db, rid)
        return receipt_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/returns/from-inspect/{inspect_id}")
def api_create_return(
    inspect_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)
):
    try:
        row = create_return_from_inspect(db, inspect_id, user=principal.username)
        db.commit()
        row, lines = get_return(db, row.id)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/returns")
def api_list_return(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_buy)):
    items = []
    for r in list_returns(db):
        _, lines = get_return(db, r.id)
        items.append(return_to_dict(r, lines))
    return {"items": items}


@router.post("/returns/{rid}/confirm")
def api_confirm_return(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_buy)):
    try:
        confirm_return(db, rid, user=principal.username)
        db.commit()
        row, lines = get_return(db, rid)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/ap-stubs")
def api_ap_stubs(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_buy)):
    return {"items": [ap_stub_to_dict(r) for r in list_ap_stubs(db)]}
