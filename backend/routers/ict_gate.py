"""ICT 开测前闸道：校验是否已过后焊。不设 EMS ICT 扫码工位。"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from board_gate import STATION_POST_SOLDER, has_station, norm_barcode
from config import load_config
from database import get_db

router = APIRouter(prefix="/api/ict-gate", tags=["ict-gate"])


def _expected_api_key() -> str:
    cfg = load_config().get("ict") or {}
    key = (cfg.get("gate_api_key") or "").strip()
    return key


def require_ict_gate_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
    api_key: Optional[str] = Query(default=None, description="兼容查询参数"),
) -> None:
    expected = _expected_api_key()
    if not expected:
        raise HTTPException(status_code=503, detail="未配置 ict.gate_api_key")
    provided = (x_api_key or api_key or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="无效的 API Key")


class IctGateCheckIn(BaseModel):
    barcode: str = Field(..., min_length=1, max_length=128)


@router.get("/check")
def check_get(
    barcode: str = Query(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
    _: None = Depends(require_ict_gate_key),
):
    return _check(db, barcode)


@router.post("/check")
def check_post(
    body: IctGateCheckIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_ict_gate_key),
):
    return _check(db, body.barcode)


def _check(db: Session, barcode: str) -> dict:
    code = norm_barcode(barcode)
    if not code:
        return {
            "allowed": False,
            "barcode": "",
            "message": "条码不能为空",
            "reason": "empty",
        }
    if has_station(db, code, STATION_POST_SOLDER):
        return {
            "allowed": True,
            "barcode": code,
            "message": "已过后焊，允许 ICT 测试",
            "reason": "ok",
        }
    return {
        "allowed": False,
        "barcode": code,
        "message": "未过后焊工序",
        "reason": "no_post_solder",
    }


@router.get("/health")
def health(_: None = Depends(require_ict_gate_key)):
    return {"status": "ok", "service": "ict-gate"}
