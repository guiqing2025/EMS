"""独立订单报价 API（仅 WGQ / dx001）"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from quotation_export import export_quote_xlsx
from quotation_service import (
    create_quote,
    delete_quote,
    get_quote,
    import_bom_and_calc,
    list_quotes,
    quote_detail_dict,
    set_status,
    update_cost_lines,
    update_quote_header,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(prefix="/api/quotation", tags=["quotation"])

QUOTE_ALLOWED_USERS = {"wgq", "dx001"}
QUOTE_ALLOWED_ROLES = frozenset({"admin", "sales", "pmc"})


def require_quote_access(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if name in QUOTE_ALLOWED_USERS or principal.role in QUOTE_ALLOWED_ROLES:
        return principal
    raise HTTPException(status_code=403, detail="无订单报价模块权限")


class QuoteCreateIn(BaseModel):
    customer_name: str = ""
    product_name: str = ""
    product_code: str = ""
    remark: str = ""
    batch_qty: float = 0


class QuoteHeaderIn(BaseModel):
    customer_name: Optional[str] = None
    product_name: Optional[str] = None
    product_code: Optional[str] = None
    remark: Optional[str] = None
    batch_qty: Optional[float] = None
    engineering_fee: Optional[float] = None


class CostPatchIn(BaseModel):
    item_key: str
    amount: Optional[float] = None
    qty: Optional[float] = None
    points: Optional[float] = None
    unit_price: Optional[float] = None


class CostLinesIn(BaseModel):
    lines: List[CostPatchIn] = Field(default_factory=list)


class StatusIn(BaseModel):
    status: str


@router.get("")
def api_list_quotes(
    keyword: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    rows = list_quotes(db, keyword=keyword, status=status)
    return [
        {
            "id": r.id,
            "quote_no": r.quote_no,
            "customer_name": r.customer_name,
            "product_name": r.product_name,
            "product_code": r.product_code,
            "status": r.status,
            "unit_price": r.unit_price,
            "tooling_total": r.tooling_total,
            "grand_total": r.grand_total,
            "batch_qty": r.batch_qty,
            "source_filename": r.source_filename,
            "created_by": r.created_by,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("")
def api_create_quote(
    body: QuoteCreateIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    row = create_quote(
        db,
        customer_name=body.customer_name,
        product_name=body.product_name,
        product_code=body.product_code,
        remark=body.remark,
        batch_qty=body.batch_qty,
        username=principal.username,
    )
    db.commit()
    db.refresh(row)
    return quote_detail_dict(db, row)


@router.get("/{quote_id}")
def api_get_quote(
    quote_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    row = get_quote(db, quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="报价单不存在")
    return quote_detail_dict(db, row)


@router.put("/{quote_id}")
def api_update_quote(
    quote_id: int,
    body: QuoteHeaderIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    try:
        row = update_quote_header(
            db,
            quote_id,
            customer_name=body.customer_name,
            product_name=body.product_name,
            product_code=body.product_code,
            remark=body.remark,
            batch_qty=body.batch_qty,
            engineering_fee=body.engineering_fee,
            username=principal.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return quote_detail_dict(db, row)


@router.post("/{quote_id}/import-bom")
async def api_import_bom(
    quote_id: int,
    file: UploadFile = File(...),
    tangxi: Optional[float] = Query(default=None),
    stencil_qty: float = Query(default=1),
    wave_fixture_qty: float = Query(default=0),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        row = import_bom_and_calc(
            db,
            quote_id,
            data,
            filename=file.filename or "",
            username=principal.username,
            tangxi=tangxi,
            stencil_qty=stencil_qty,
            wave_fixture_qty=wave_fixture_qty,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"BOM 解析失败：{e}")
    db.commit()
    return quote_detail_dict(db, row)


@router.put("/{quote_id}/cost-lines")
def api_patch_costs(
    quote_id: int,
    body: CostLinesIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    try:
        row = update_cost_lines(
            db,
            quote_id,
            [x.model_dump() for x in body.lines],
            username=principal.username,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return quote_detail_dict(db, row)


@router.post("/{quote_id}/status")
def api_set_status(
    quote_id: int,
    body: StatusIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    try:
        row = set_status(db, quote_id, body.status, username=principal.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return quote_detail_dict(db, row)


@router.delete("/{quote_id}")
def api_delete_quote(
    quote_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    try:
        delete_quote(db, quote_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.commit()
    return {"message": "已删除"}


@router.get("/{quote_id}/export")
def api_export(
    quote_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quote_access),
):
    row = get_quote(db, quote_id)
    if not row:
        raise HTTPException(status_code=404, detail="报价单不存在")
    data = export_quote_xlsx(db, row)
    filename = f"{row.quote_no}_{(row.product_code or 'quote')}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
