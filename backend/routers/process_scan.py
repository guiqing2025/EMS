"""产线工序扫码：插件 / 后焊 / 三防"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from process_scan_service import (
    STATION_LABELS,
    list_scans_for_purchase,
    scan_process,
)
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
    operator: str = ""


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
    operator = (body.operator or principal.display_name or principal.username or "").strip()
    try:
        result = scan_process(
            db,
            station=body.station,
            barcode=body.barcode,
            operator=operator,
            purchase_no=body.purchase_no,
        )
        if result.get("status") in ("ok", "already_scanned"):
            # already_scanned 无写入；ok 需提交
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
