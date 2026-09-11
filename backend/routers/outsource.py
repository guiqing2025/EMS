"""委外执行链 API"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from outsource_service import (
    confirm_return,
    confirm_ship,
    create_inspect_from_ww,
    create_receipt_from_inspect,
    create_return_from_inspect,
    create_ship_from_ww,
    create_ww,
    create_ww_from_plan,
    get_inspect,
    get_receipt,
    get_return,
    get_ship,
    get_ww,
    inspect_to_dict,
    judge_inspect,
    list_inspects,
    list_receipts,
    list_returns,
    list_ships,
    list_ww,
    post_receipt,
    receipt_to_dict,
    register_barcode,
    return_to_dict,
    set_ww_status,
    ship_to_dict,
    ww_to_dict,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/outsource",
    tags=["outsource"],
    dependencies=[Depends(require_system_auth)],
)

OS_ROLES = frozenset({"admin", "purchasing", "production", "pmc", "planner", "quality", "warehouse"})


def require_os(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in OS_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无委外模块权限")


class LineIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"
    unit_price: float = 0
    process: str = ""
    due_date: str = ""


class WwIn(BaseModel):
    supplier_id: Optional[int] = None
    supplier_name: str = ""
    process: str = ""
    stock_owner: str = "internal"
    remark: str = ""
    lines: list[LineIn] = Field(default_factory=list)


class StatusIn(BaseModel):
    status: str


class FromPlanIn(BaseModel):
    supplier_name: str = ""
    supplier_id: Optional[int] = None


class BarcodeIn(BaseModel):
    ww_id: int
    barcode: str
    material_code: str = ""
    qty: float = 1


class JudgeLineIn(BaseModel):
    line_id: int
    pass_qty: float = 0
    fail_qty: float = 0


class JudgeIn(BaseModel):
    lines: list[JudgeLineIn] = Field(default_factory=list)


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.get("/orders")
def api_list(q: str = Query(""), status: str = Query(""), db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_os)):
    items = []
    for r in list_ww(db, q=q, status=status):
        _, lines = get_ww(db, r.id)
        items.append(ww_to_dict(r, lines))
    return {"items": items}


@router.post("/orders")
def api_create(body: WwIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        row = create_ww(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_ww(db, row.id)
        return ww_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/orders/{ww_id}/status")
def api_status(ww_id: int, body: StatusIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        set_ww_status(db, ww_id, body.status, user=principal.username)
        db.commit()
        row, lines = get_ww(db, ww_id)
        return ww_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/orders/from-plan/{plan_id}")
def api_from_plan(plan_id: int, body: FromPlanIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        row = create_ww_from_plan(db, plan_id, supplier_name=body.supplier_name, supplier_id=body.supplier_id, user=principal.username)
        db.commit()
        row, lines = get_ww(db, row.id)
        return ww_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/ships/from-order/{ww_id}")
def api_ship(ww_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        row = create_ship_from_ww(db, ww_id, user=principal.username)
        db.commit()
        row, lines = get_ship(db, row.id)
        return ship_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/ships")
def api_list_ships(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_os)):
    items = []
    for r in list_ships(db):
        _, lines = get_ship(db, r.id)
        items.append(ship_to_dict(r, lines))
    return {"items": items}


@router.post("/ships/{sid}/confirm")
def api_confirm_ship(sid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        confirm_ship(db, sid, user=principal.username)
        db.commit()
        row, lines = get_ship(db, sid)
        return ship_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/barcodes")
def api_bc(body: BarcodeIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        row = register_barcode(db, _dump(body), user=principal.username)
        db.commit()
        return {"id": row.id, "barcode": row.barcode, "ww_id": row.ww_id}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/inspects/from-order/{ww_id}")
def api_insp(ww_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        row = create_inspect_from_ww(db, ww_id, user=principal.username)
        db.commit()
        row, lines = get_inspect(db, row.id)
        return inspect_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/inspects")
def api_list_insp(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_os)):
    items = []
    for r in list_inspects(db):
        _, lines = get_inspect(db, r.id)
        items.append(inspect_to_dict(r, lines))
    return {"items": items}


@router.post("/inspects/{iid}/judge")
def api_judge(iid: int, body: JudgeIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        judge_inspect(db, iid, [_dump(x) for x in body.lines], user=principal.username)
        db.commit()
        row, lines = get_inspect(db, iid)
        return inspect_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/receipts/from-inspect/{inspect_id}")
def api_rec(inspect_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        row = create_receipt_from_inspect(db, inspect_id, user=principal.username)
        db.commit()
        row, lines = get_receipt(db, row.id)
        return receipt_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/receipts")
def api_list_rec(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_os)):
    items = []
    for r in list_receipts(db):
        _, lines = get_receipt(db, r.id)
        items.append(receipt_to_dict(r, lines))
    return {"items": items}


@router.post("/receipts/{rid}/post")
def api_post(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        post_receipt(db, rid, user=principal.username)
        db.commit()
        row, lines = get_receipt(db, rid)
        return receipt_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/returns/from-inspect/{inspect_id}")
def api_ret(inspect_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        row = create_return_from_inspect(db, inspect_id, user=principal.username)
        db.commit()
        row, lines = get_return(db, row.id)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/returns")
def api_list_ret(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_os)):
    items = []
    for r in list_returns(db):
        _, lines = get_return(db, r.id)
        items.append(return_to_dict(r, lines))
    return {"items": items}


@router.post("/returns/{rid}/confirm")
def api_confirm_ret(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_os)):
    try:
        confirm_return(db, rid, user=principal.username)
        db.commit()
        row, lines = get_return(db, rid)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
