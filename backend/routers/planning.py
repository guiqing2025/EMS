"""计划中枢 API：MRP / 三类计划 / 预告 / 库存预警 / PMC"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import CustomerForecastLine, PurchaseForecastLine
from planning_service import (
    create_customer_forecast,
    create_purchase_forecast,
    customer_forecast_to_dict,
    generate_mrp,
    get_outsource_plan,
    get_production_plan,
    get_purchase_plan,
    list_customer_forecasts,
    list_mrp_runs,
    list_outsource_plans,
    list_production_plans,
    list_purchase_forecasts,
    list_purchase_plans,
    mrp_run_to_dict,
    outsource_plan_to_dict,
    pmc_board,
    pmc_urge,
    preview_mrp,
    production_plan_to_dict,
    purchase_forecast_to_dict,
    purchase_plan_to_dict,
    run_mc_kitting,
    set_customer_forecast_status,
    set_outsource_plan_status,
    set_production_plan_status,
    set_purchase_forecast_status,
    set_purchase_plan_status,
    stock_warnings,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/planning",
    tags=["planning"],
    dependencies=[Depends(require_system_auth)],
)

PLAN_ROLES = frozenset({"admin", "pmc", "planner", "sales", "purchasing", "production"})


def require_plan(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in PLAN_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无计划模块权限")


class MrpIn(BaseModel):
    so_ids: list[int] = Field(default_factory=list)
    stock_ids: list[int] = Field(default_factory=list)
    include_forecasts: bool = False
    advance_status: bool = True


class StatusIn(BaseModel):
    status: str


class ForecastLineIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"
    due_date: str = ""
    bom_model_id: Optional[int] = None
    remark: str = ""


class CustomerForecastIn(BaseModel):
    customer_id: Optional[int] = None
    customer_name: str = ""
    remark: str = ""
    lines: list[ForecastLineIn] = Field(default_factory=list)


class PurchaseForecastIn(BaseModel):
    supplier_name: str = ""
    remark: str = ""
    lines: list[ForecastLineIn] = Field(default_factory=list)


class McKittingIn(BaseModel):
    so_ids: list[int] = Field(default_factory=list)
    q: str = ""


@router.post("/mc-kitting/run")
def api_mc_kitting_run(body: McKittingIn, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    try:
        return run_mc_kitting(db, so_ids=body.so_ids or None, q=body.q or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/mc-kitting/run")
def api_mc_kitting_run_get(
    q: str = "",
    so_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_plan),
):
    try:
        ids = [so_id] if so_id else None
        return run_mc_kitting(db, so_ids=ids, q=q or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/mrp/preview")
def api_mrp_preview(body: MrpIn, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    try:
        return preview_mrp(
            db,
            so_ids=body.so_ids or None,
            stock_ids=body.stock_ids or None,
            include_forecasts=body.include_forecasts,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/mrp/generate")
def api_mrp_generate(
    body: MrpIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_plan)
):
    try:
        result = generate_mrp(
            db,
            so_ids=body.so_ids or None,
            stock_ids=body.stock_ids or None,
            include_forecasts=body.include_forecasts,
            advance_status=body.advance_status,
            user=principal.username,
        )
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/mrp/runs")
def api_mrp_runs(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    return {"items": [mrp_run_to_dict(r) for r in list_mrp_runs(db)]}


@router.get("/stock-warnings")
def api_stock_warnings(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    return {"items": stock_warnings(db)}


@router.get("/pmc-board")
def api_pmc_board(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    return {"items": pmc_board(db)}


class UrgeIn(BaseModel):
    note: str = ""


@router.post("/pmc-board/{so_id}/urge")
def api_pmc_urge(
    so_id: int,
    body: UrgeIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_plan),
):
    try:
        out = pmc_urge(db, so_id, user=principal.username or "", note=body.note or "")
        db.commit()
        return out
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


# —— 采购计划 ——


@router.get("/purchase-plans")
def api_list_pur(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    items = []
    for r in list_purchase_plans(db):
        _, lines = get_purchase_plan(db, r.id)
        items.append(purchase_plan_to_dict(r, lines))
    return {"items": items}


@router.get("/purchase-plans/{pid}")
def api_get_pur(pid: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    try:
        row, lines = get_purchase_plan(db, pid)
        return purchase_plan_to_dict(row, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/purchase-plans/{pid}/status")
def api_pur_status(
    pid: int, body: StatusIn, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)
):
    try:
        set_purchase_plan_status(db, pid, body.status)
        db.commit()
        row, lines = get_purchase_plan(db, pid)
        return purchase_plan_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


# —— 生产计划 ——


@router.get("/production-plans")
def api_list_prod(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    items = []
    for r in list_production_plans(db):
        _, lines = get_production_plan(db, r.id)
        items.append(production_plan_to_dict(r, lines))
    return {"items": items}


@router.get("/production-plans/{pid}")
def api_get_prod(pid: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    try:
        row, lines = get_production_plan(db, pid)
        return production_plan_to_dict(row, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/production-plans/{pid}/status")
def api_prod_status(
    pid: int, body: StatusIn, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)
):
    try:
        set_production_plan_status(db, pid, body.status)
        db.commit()
        row, lines = get_production_plan(db, pid)
        return production_plan_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


# —— 委外计划 ——


@router.get("/outsource-plans")
def api_list_outs(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    items = []
    for r in list_outsource_plans(db):
        _, lines = get_outsource_plan(db, r.id)
        items.append(outsource_plan_to_dict(r, lines))
    return {"items": items}


@router.get("/outsource-plans/{pid}")
def api_get_outs(pid: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    try:
        row, lines = get_outsource_plan(db, pid)
        return outsource_plan_to_dict(row, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/outsource-plans/{pid}/status")
def api_outs_status(
    pid: int, body: StatusIn, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)
):
    try:
        set_outsource_plan_status(db, pid, body.status)
        db.commit()
        row, lines = get_outsource_plan(db, pid)
        return outsource_plan_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


# —— 预告 ——


@router.get("/customer-forecasts")
def api_list_cf(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    items = []
    for r in list_customer_forecasts(db):
        lines = (
            db.query(CustomerForecastLine)
            .filter(CustomerForecastLine.forecast_id == r.id)
            .order_by(CustomerForecastLine.sort_order)
            .all()
        )
        items.append(customer_forecast_to_dict(r, lines))
    return {"items": items}


@router.post("/customer-forecasts")
def api_create_cf(
    body: CustomerForecastIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_plan)
):
    try:
        data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        row = create_customer_forecast(db, data, user=principal.username)
        db.commit()
        lines = db.query(CustomerForecastLine).filter(CustomerForecastLine.forecast_id == row.id).all()
        return customer_forecast_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/customer-forecasts/{fid}/status")
def api_cf_status(
    fid: int, body: StatusIn, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)
):
    try:
        row = set_customer_forecast_status(db, fid, body.status)
        db.commit()
        lines = db.query(CustomerForecastLine).filter(CustomerForecastLine.forecast_id == row.id).all()
        return customer_forecast_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/purchase-forecasts")
def api_list_pf(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    items = []
    for r in list_purchase_forecasts(db):
        lines = (
            db.query(PurchaseForecastLine)
            .filter(PurchaseForecastLine.forecast_id == r.id)
            .order_by(PurchaseForecastLine.sort_order)
            .all()
        )
        items.append(purchase_forecast_to_dict(r, lines))
    return {"items": items}


@router.post("/purchase-forecasts")
def api_create_pf(
    body: PurchaseForecastIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_plan)
):
    try:
        data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        row = create_purchase_forecast(db, data, user=principal.username)
        db.commit()
        lines = db.query(PurchaseForecastLine).filter(PurchaseForecastLine.forecast_id == row.id).all()
        return purchase_forecast_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/purchase-forecasts/{fid}/status")
def api_pf_status(
    fid: int, body: StatusIn, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)
):
    try:
        row = set_purchase_forecast_status(db, fid, body.status)
        db.commit()
        lines = db.query(PurchaseForecastLine).filter(PurchaseForecastLine.forecast_id == row.id).all()
        return purchase_forecast_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


# —— 工程 BOM（流程图：销售/MRP 用，不走旧 SRM 客户工作台）——

from bom_erp_service import (  # noqa: E402
    bom_to_dict,
    create_bom,
    deactivate_bom,
    get_bom,
    list_boms,
    update_bom,
)


class BomLineIn(BaseModel):
    seq: str = ""
    material_code: str = ""
    material_name: str = ""
    spec: str = ""
    unit: str = "PCS"
    qty_per: float = 1
    position: str = ""
    process: str = ""
    remark: str = ""
    sort_order: int = 0


class BomIn(BaseModel):
    internal_code: str = "ERP"
    customer_id: str = "internal"
    customer_name: str = ""
    model_code: str = ""
    model_name: str = ""
    model_spec: str = ""
    purchase_no: str = ""
    remark: str = ""
    is_active: Optional[bool] = None
    lines: list[BomLineIn] = Field(default_factory=list)


@router.get("/boms")
def api_list_boms(
    q: str = "",
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_plan),
):
    rows = list_boms(db, q=q, active_only=active_only)
    return {"items": [bom_to_dict(r) for r in rows]}


@router.get("/boms/{bom_id}")
def api_get_bom(bom_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    try:
        bom, lines = get_bom(db, bom_id)
        return bom_to_dict(bom, lines)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/boms")
def api_create_bom(body: BomIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_plan)):
    try:
        data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        bom = create_bom(db, data, user=principal.username or "")
        db.commit()
        bom, lines = get_bom(db, bom.id)
        return bom_to_dict(bom, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put("/boms/{bom_id}")
def api_update_bom(
    bom_id: int, body: BomIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_plan)
):
    try:
        data = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        update_bom(db, bom_id, data, user=principal.username or "")
        db.commit()
        bom, lines = get_bom(db, bom_id)
        return bom_to_dict(bom, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/boms/{bom_id}/deactivate")
def api_deactivate_bom(bom_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_plan)):
    try:
        bom = deactivate_bom(db, bom_id)
        db.commit()
        return bom_to_dict(bom)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
