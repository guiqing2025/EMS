"""仓储辅助 API：盘点 / 调拨 / 库存出库"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from system_auth import AuthPrincipal, require_system_auth
from warehouse_aux_service import (
    create_stocktake,
    create_transfer,
    get_stocktake,
    get_transfer,
    list_stocktakes,
    list_transfers,
    post_stocktake,
    post_transfer,
    stocktake_to_dict,
    transfer_to_dict,
)

router = APIRouter(
    prefix="/api/warehouse-aux",
    tags=["warehouse-aux"],
    dependencies=[Depends(require_system_auth)],
)

WH_ROLES = frozenset({"admin", "warehouse", "pmc", "planner"})


def require_wh(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in WH_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无仓储辅助权限")


class StLine(BaseModel):
    material_code: str
    material_name: str = ""
    book_qty: Optional[float] = None
    count_qty: float = 0
    unit: str = "PCS"


class StocktakeIn(BaseModel):
    stock_owner: str = "internal"
    remark: str = ""
    lines: list[StLine] = Field(default_factory=list)


class TfLine(BaseModel):
    material_code: str
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"


class TransferIn(BaseModel):
    kind: str = "transfer"
    from_owner: str = "internal"
    to_owner: str = ""
    remark: str = ""
    lines: list[TfLine] = Field(default_factory=list)


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.get("/stocktakes")
def api_list_st(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_wh)):
    items = []
    for r in list_stocktakes(db):
        _, lines = get_stocktake(db, r.id)
        items.append(stocktake_to_dict(r, lines))
    return {"items": items}


@router.post("/stocktakes")
def api_create_st(body: StocktakeIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_wh)):
    try:
        row = create_stocktake(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_stocktake(db, row.id)
        return stocktake_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/stocktakes/{sid}/post")
def api_post_st(sid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_wh)):
    try:
        post_stocktake(db, sid, user=principal.username)
        db.commit()
        row, lines = get_stocktake(db, sid)
        return stocktake_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/transfers")
def api_list_tf(kind: str = Query(""), db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_wh)):
    items = []
    for r in list_transfers(db, kind=kind):
        _, lines = get_transfer(db, r.id)
        items.append(transfer_to_dict(r, lines))
    return {"items": items}


@router.post("/transfers")
def api_create_tf(body: TransferIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_wh)):
    try:
        row = create_transfer(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_transfer(db, row.id)
        return transfer_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/transfers/{tid}/post")
def api_post_tf(tid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_wh)):
    try:
        post_transfer(db, tid, user=principal.username)
        db.commit()
        row, lines = get_transfer(db, tid)
        return transfer_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
