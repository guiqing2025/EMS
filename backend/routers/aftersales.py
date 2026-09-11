"""售后 API：投诉 / 销退补发补货 / 借样还入转销售"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from aftersales_service import (
    branch_reissue,
    branch_replenish,
    complaint_to_dict,
    confirm_return,
    convert_loan_to_so,
    create_complaint,
    create_return_from_delivery,
    create_return_from_issue,
    get_return,
    list_complaints,
    list_returns,
    return_loan,
    return_to_dict,
    set_complaint_status,
)
from database import get_db
from models import SampleLoan
from presales_service import loan_to_dict, list_loans
from sales_service import sales_order_to_dict, get_sales_order
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/aftersales",
    tags=["aftersales"],
    dependencies=[Depends(require_system_auth)],
)

AS_ROLES = frozenset({"admin", "sales", "warehouse", "quality", "pmc", "planner", "production"})


def require_as(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in AS_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无售后模块权限")


class ComplaintIn(BaseModel):
    so_id: Optional[int] = None
    delivery_id: Optional[int] = None
    so_no: str = ""
    delivery_no: str = ""
    customer_name: str = ""
    title: str
    content: str = ""
    remark: str = ""


class StatusIn(BaseModel):
    status: str


class ConvertIn(BaseModel):
    unit_price: float = 0


class ReturnLoanIn(BaseModel):
    restock: bool = True


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.get("/complaints")
def api_list_c(q: str = Query(""), db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_as)):
    return {"items": [complaint_to_dict(r) for r in list_complaints(db, q=q)]}


@router.post("/complaints")
def api_create_c(body: ComplaintIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        row = create_complaint(db, _dump(body), user=principal.username)
        db.commit()
        return complaint_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/complaints/{cid}/status")
def api_c_status(cid: int, body: StatusIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        row = set_complaint_status(db, cid, body.status, user=principal.username)
        db.commit()
        return complaint_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/returns")
def api_list_r(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_as)):
    items = []
    for r in list_returns(db):
        _, lines = get_return(db, r.id)
        items.append(return_to_dict(r, lines))
    return {"items": items}


@router.post("/returns/from-issue/{issue_id}")
def api_r_issue(issue_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        row = create_return_from_issue(db, issue_id, user=principal.username)
        db.commit()
        row, lines = get_return(db, row.id)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/returns/from-delivery/{delivery_id}")
def api_r_del(delivery_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        row = create_return_from_delivery(db, delivery_id, user=principal.username)
        db.commit()
        row, lines = get_return(db, row.id)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/returns/{rid}/confirm")
def api_r_confirm(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        confirm_return(db, rid, user=principal.username)
        db.commit()
        row, lines = get_return(db, rid)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/returns/{rid}/reissue")
def api_reissue(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        branch_reissue(db, rid, user=principal.username)
        db.commit()
        row, lines = get_return(db, rid)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/returns/{rid}/replenish")
def api_replenish(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        branch_replenish(db, rid, user=principal.username)
        db.commit()
        row, lines = get_return(db, rid)
        return return_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/sample-loans")
def api_loans(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_as)):
    return {"items": [loan_to_dict(r) for r in list_loans(db)]}


@router.post("/sample-loans/{lid}/return")
def api_loan_ret(lid: int, body: ReturnLoanIn = ReturnLoanIn(), db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        row = return_loan(db, lid, user=principal.username, restock=body.restock)
        db.commit()
        return loan_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sample-loans/{lid}/convert")
def api_loan_conv(lid: int, body: ConvertIn = ConvertIn(), db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_as)):
    try:
        so = convert_loan_to_so(db, lid, user=principal.username, unit_price=body.unit_price)
        db.commit()
        so, lines = get_sales_order(db, so.id)
        loan = db.query(SampleLoan).filter(SampleLoan.id == lid).first()
        return {"loan": loan_to_dict(loan) if loan else None, "sales_order": sales_order_to_dict(so, lines)}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
