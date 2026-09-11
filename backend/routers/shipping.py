"""销售出货 API：销售出库 / 打包条码 / 发货单"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from shipping_service import (
    confirm_delivery,
    create_delivery_from_issue,
    create_issue,
    create_issue_from_fg,
    create_issue_from_so,
    delivery_print_payload,
    delivery_to_dict,
    get_delivery,
    get_issue,
    issue_to_dict,
    list_deliveries,
    list_issues,
    list_pack_barcodes,
    post_issue,
    register_pack_barcode,
    void_issue,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/shipping",
    tags=["shipping"],
    dependencies=[Depends(require_system_auth)],
)

SHIP_ROLES = frozenset({"admin", "warehouse", "sales", "packing", "pmc", "planner"})


def require_ship(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in SHIP_ROLES or name in {"wgq", "dx001", "dxbz001", "dxbz002"}:
        return principal
    raise HTTPException(status_code=403, detail="无出货模块权限")


class LineIn(BaseModel):
    so_line_id: Optional[int] = None
    material_code: str = ""
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"
    unit_price: float = 0


class IssueIn(BaseModel):
    so_id: Optional[int] = None
    so_no: str = ""
    customer_name: str = ""
    stock_owner: str = "internal"
    remark: str = ""
    lines: list[LineIn] = Field(default_factory=list)


class FromSoIn(BaseModel):
    line_qtys: list[dict] = Field(default_factory=list)


class BarcodeIn(BaseModel):
    issue_id: int
    barcode: str
    material_code: str = ""
    qty: float = 1
    box_no: str = ""


class DeliveryIn(BaseModel):
    carrier: str = ""
    tracking_no: str = ""
    ship_date: str = ""


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.get("/issues")
def api_list_issues(q: str = Query(""), status: str = Query(""), db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_ship)):
    items = []
    for r in list_issues(db, q=q, status=status):
        _, lines = get_issue(db, r.id)
        items.append(issue_to_dict(r, lines))
    return {"items": items}


@router.post("/issues")
def api_create_issue(body: IssueIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        row = create_issue(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_issue(db, row.id)
        return issue_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/issues/from-so/{so_id}")
def api_from_so(so_id: int, body: FromSoIn = FromSoIn(), db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        row = create_issue_from_so(db, so_id, user=principal.username, line_qtys=body.line_qtys or None)
        db.commit()
        row, lines = get_issue(db, row.id)
        return issue_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/issues/from-fg/{fg_id}")
def api_from_fg(fg_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        row = create_issue_from_fg(db, fg_id, user=principal.username)
        db.commit()
        row, lines = get_issue(db, row.id)
        return issue_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/issues/{issue_id}/post")
def api_post(issue_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        post_issue(db, issue_id, user=principal.username)
        db.commit()
        row, lines = get_issue(db, issue_id)
        return issue_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/issues/{issue_id}/void")
def api_void(issue_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        void_issue(db, issue_id, user=principal.username)
        db.commit()
        row, lines = get_issue(db, issue_id)
        return issue_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/pack-barcodes")
def api_pack(body: BarcodeIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        row = register_pack_barcode(db, _dump(body), user=principal.username)
        db.commit()
        return {"id": row.id, "barcode": row.barcode, "issue_id": row.issue_id, "box_no": row.box_no}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/issues/{issue_id}/pack-barcodes")
def api_list_pack(issue_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_ship)):
    rows = list_pack_barcodes(db, issue_id)
    return {
        "items": [
            {"id": r.id, "barcode": r.barcode, "material_code": r.material_code, "qty": r.qty, "box_no": r.box_no}
            for r in rows
        ]
    }


@router.post("/deliveries/from-issue/{issue_id}")
def api_del_from(issue_id: int, body: DeliveryIn = DeliveryIn(), db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        row = create_delivery_from_issue(
            db,
            issue_id,
            user=principal.username,
            carrier=body.carrier,
            tracking_no=body.tracking_no,
            ship_date=body.ship_date,
        )
        db.commit()
        row, lines = get_delivery(db, row.id)
        return delivery_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/deliveries")
def api_list_del(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_ship)):
    items = []
    for r in list_deliveries(db):
        _, lines = get_delivery(db, r.id)
        items.append(delivery_to_dict(r, lines))
    return {"items": items}


@router.post("/deliveries/{did}/confirm")
def api_confirm_del(did: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_ship)):
    try:
        confirm_delivery(db, did, user=principal.username)
        db.commit()
        row, lines = get_delivery(db, did)
        return delivery_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/deliveries/{did}/print")
def api_print(did: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_ship)):
    try:
        return delivery_print_payload(db, did)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
