"""总账 API"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from gl_service import (
    account_to_dict,
    asset_to_dict,
    close_period,
    close_pnl,
    create_cost_accrual,
    create_fixed_asset,
    create_voucher,
    depreciate_asset,
    ensure_gl_seed,
    fx_adjustment,
    get_voucher,
    list_accounts,
    list_assets,
    list_periods,
    list_vouchers,
    period_to_dict,
    post_voucher,
    review_voucher,
    voucher_to_dict,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/finance/gl",
    tags=["gl"],
    dependencies=[Depends(require_system_auth)],
)

FIN_ROLES = frozenset({"admin", "finance", "pmc"})


def require_fin(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in FIN_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无财务权限")


class VLine(BaseModel):
    account_code: str
    debit: float = 0
    credit: float = 0
    summary: str = ""


class VoucherIn(BaseModel):
    period: str = ""
    summary: str = ""
    lines: list[VLine] = Field(default_factory=list)


class CostIn(BaseModel):
    amount: float
    remark: str = ""


class AssetIn(BaseModel):
    name: str = "固定资产"
    original_value: float
    residual_rate: float = 0.05
    months: int = 36
    remark: str = ""


class PeriodIn(BaseModel):
    period: str = ""


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.post("/bootstrap")
def api_boot(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    out = ensure_gl_seed(db, opening=True)
    db.commit()
    return out


@router.get("/accounts")
def api_acc(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [account_to_dict(r) for r in list_accounts(db)]}


@router.get("/periods")
def api_periods(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [period_to_dict(r) for r in list_periods(db)]}


@router.get("/vouchers")
def api_list_v(
    period: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_fin),
):
    items = []
    for r in list_vouchers(db, period=period, status=status):
        _, lines = get_voucher(db, r.id)
        items.append(voucher_to_dict(r, lines))
    return {"items": items}


@router.post("/vouchers")
def api_create_v(body: VoucherIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_voucher(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_voucher(db, row.id)
        return voucher_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/vouchers/{vid}/review")
def api_review(vid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        review_voucher(db, vid, user=principal.username)
        db.commit()
        row, lines = get_voucher(db, vid)
        return voucher_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/vouchers/{vid}/post")
def api_post(vid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        post_voucher(db, vid, user=principal.username)
        db.commit()
        row, lines = get_voucher(db, vid)
        return voucher_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/cost-accrual")
def api_cost(body: CostIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_cost_accrual(db, amount=body.amount, user=principal.username, remark=body.remark)
        db.commit()
        row, lines = get_voucher(db, row.id)
        return voucher_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/assets")
def api_assets(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [asset_to_dict(r) for r in list_assets(db)]}


@router.post("/assets")
def api_create_asset(body: AssetIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_fixed_asset(db, _dump(body), user=principal.username)
        db.commit()
        return asset_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/assets/{aid}/depreciate")
def api_depr(aid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        v = depreciate_asset(db, aid, user=principal.username)
        db.commit()
        row, lines = get_voucher(db, v.id)
        return voucher_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/fx-adjust")
def api_fx(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    return fx_adjustment(db, user=principal.username)


@router.post("/close-pnl")
def api_pnl(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        v = close_pnl(db, user=principal.username)
        db.commit()
        row, lines = get_voucher(db, v.id)
        return voucher_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/close-period")
def api_close(body: PeriodIn = PeriodIn(), db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        p = close_period(db, user=principal.username, period=body.period)
        db.commit()
        return period_to_dict(p)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
