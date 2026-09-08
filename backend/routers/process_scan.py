"""产线工序扫码：插件 / 后焊 / 三防；SMT 人工扫码（与 AOI 等效）"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from process_scan_service import (
    STATION_LABELS,
    backfill_process_scan_model_codes,
    list_scans_for_purchase,
    scan_process,
)
from scan_station_policy import assert_scan_kind_allowed
from smt_scan_service import scan_smt_manual
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/process-scan",
    tags=["process-scan"],
    dependencies=[Depends(require_system_auth)],
)


class ProcessScanIn(BaseModel):
    station: str = Field(..., description="plugin / post_solder / coating")
    barcode: str
    purchase_no: str = ""
    model_code: str = ""
    operator: str = ""


class SmtScanIn(BaseModel):
    barcode: str
    result: str = Field(..., description="PASS / FAIL")
    purchase_no: str = ""
    model_code: str = ""
    operator: str = ""


class PreOvenLineConfirmIn(BaseModel):
    barcode: str = Field(..., min_length=4, max_length=64)
    action: str = Field(..., description="pass / fail")
    purchase_no: str = ""
    model_code: str = ""
    remark: str = Field("", max_length=512)


@router.get("/stations")
def api_stations():
    return [{"id": k, "label": v} for k, v in STATION_LABELS.items()]


@router.post("/scan")
def api_scan(
    body: ProcessScanIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    if principal.role == "packing":
        raise HTTPException(status_code=403, detail="包装账号仅可使用包装入库扫码")
    if principal.role == "smt_scan":
        raise HTTPException(status_code=403, detail="SMT扫码账号仅可使用 SMT 人工扫码")
    assert_scan_kind_allowed(principal, body.station)
    operator = (principal.username or principal.display_name or body.operator or "").strip()
    try:
        result = scan_process(
            db,
            station=body.station,
            barcode=body.barcode,
            operator=operator,
            purchase_no=body.purchase_no,
            model_code=body.model_code,
        )
        if result.get("status") in ("ok", "already_scanned"):
            if result.get("status") == "ok":
                db.commit()
            else:
                db.rollback()
        else:
            db.rollback()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/pre-oven-aoi/line-confirm")
def api_pre_oven_line_confirm(
    body: PreOvenLineConfirmIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """后焊产线：炉前 AOI 真不良复判（独立于 /scan 热路径）。"""
    if principal.role == "packing":
        raise HTTPException(status_code=403, detail="包装账号不可操作")
    if principal.role == "smt_scan":
        raise HTTPException(status_code=403, detail="SMT扫码账号不可操作")
    assert_scan_kind_allowed(principal, "post_solder")
    operator = (principal.username or principal.display_name or "").strip()
    try:
        from pre_oven_aoi_qc_service import line_confirm

        result = line_confirm(
            db,
            barcode=body.barcode,
            action=body.action,
            operator=operator,
            purchase_no=body.purchase_no,
            model_code=body.model_code,
            remark=body.remark or "",
        )
        db.commit()
        return result
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/smt")
def api_smt_scan(
    body: SmtScanIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    if principal.role == "packing":
        raise HTTPException(status_code=403, detail="包装账号仅可使用包装入库扫码")
    assert_scan_kind_allowed(principal, "smt")
    operator = (body.operator or principal.display_name or principal.username or "").strip()
    try:
        result = scan_smt_manual(
            db,
            barcode=body.barcode,
            result=body.result,
            purchase_no=body.purchase_no,
            model_code=body.model_code,
            operator=operator,
        )
        if result.get("status") == "ok" and result.get("is_new"):
            db.commit()
        else:
            db.rollback()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/backfill-model")
def api_backfill_model(
    limit: int = Query(50000, ge=1, le=200000),
    rematch_laser: bool = Query(False, description="是否先按贴码/镭雕重挂（较慢）"),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """补全历史缺机型扫码，使订单列表插件/后焊/三防数量刷新后仍可见。"""
    if principal.role in ("packing", "smt_scan"):
        raise HTTPException(status_code=403, detail="无此权限")
    try:
        result = backfill_process_scan_model_codes(db, limit=limit, rematch_laser=rematch_laser)
        db.commit()
        return {"status": "ok", **result}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/orders/{purchase_no}")
def api_list_order_scans(
    purchase_no: str,
    station: str = "",
    keyword: str = "",
    limit: int = Query(3000, ge=1, le=20000),
    db: Session = Depends(get_db),
):
    return list_scans_for_purchase(
        db,
        purchase_no,
        station=station,
        keyword=keyword,
        limit=limit,
    )
