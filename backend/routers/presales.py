"""售前 API：询价 / 设计打样 / 样品邮寄 / 借样 / 报价转单"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import ErpSalesOrderLine, QuoteOrder
from presales_service import (
    create_design,
    create_design_from_quote,
    create_inquiry,
    create_loan,
    create_mail,
    create_quote_from_inquiry,
    create_sample_order,
    create_sample_order_from_quote,
    create_sales_order_from_quote,
    design_to_dict,
    get_inquiry,
    inquiry_to_dict,
    list_designs,
    list_inquiries,
    list_loans,
    list_mails,
    list_sales_orders,
    list_sample_orders,
    loan_to_dict,
    mail_to_dict,
    sample_order_to_dict,
    sales_order_to_dict,
    update_design,
    update_inquiry,
    update_loan,
    update_mail,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/presales",
    tags=["presales"],
    dependencies=[Depends(require_system_auth)],
)

PRESALES_ROLES = frozenset({"admin", "sales", "pmc", "planner"})


def require_presales(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in PRESALES_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无售前模块权限")


class LineIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    spec: str = ""
    qty: float = 0
    unit: str = "PCS"
    remark: str = ""


class InquiryIn(BaseModel):
    customer_id: Optional[int] = None
    customer_name: str = ""
    contact: str = ""
    phone: str = ""
    title: str = ""
    remark: str = ""
    status: Optional[str] = None
    lines: list[LineIn] = Field(default_factory=list)


class DesignIn(BaseModel):
    inquiry_id: Optional[int] = None
    quote_id: Optional[int] = None
    customer_name: str = ""
    product_code: str = ""
    product_name: str = ""
    owner: str = ""
    remark: str = ""
    status: Optional[str] = None


class SampleOrderIn(BaseModel):
    inquiry_id: Optional[int] = None
    quote_id: Optional[int] = None
    design_id: Optional[int] = None
    customer_id: Optional[int] = None
    customer_name: str = ""
    product_code: str = ""
    product_name: str = ""
    qty: float = 1
    remark: str = ""
    status: Optional[str] = None


class MailIn(BaseModel):
    inquiry_id: Optional[int] = None
    customer_name: str = ""
    product_name: str = ""
    channel: str = "mail"
    tracking_no: str = ""
    link_url: str = ""
    status: Optional[str] = None
    sent_at: str = ""
    remark: str = ""


class LoanIn(BaseModel):
    customer_id: Optional[int] = None
    customer_name: str = ""
    product_code: str = ""
    product_name: str = ""
    qty: float = 1
    status: Optional[str] = None
    lent_at: str = ""
    expect_return_at: str = ""
    returned_at: str = ""
    remark: str = ""


class QuoteLinkIn(BaseModel):
    supplier_name: str = ""
    supplier_cost: float = 0
    sell_price: float = 0
    quote_kind: str = "cost"
    inquiry_id: Optional[int] = None
    customer_id: Optional[int] = None


def _err(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc) or "操作失败")


# —— 询价 ——


@router.get("/inquiries")
def api_list_inquiries(
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_presales),
):
    rows = list_inquiries(db, q=q, status=status)
    return {"items": [inquiry_to_dict(r) for r in rows]}


@router.get("/inquiries/{iid}")
def api_get_inquiry(iid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)):
    try:
        row, lines = get_inquiry(db, iid)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return inquiry_to_dict(row, lines)


@router.post("/inquiries")
def api_create_inquiry(
    body: InquiryIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    row = create_inquiry(db, body.model_dump(), user=principal.username)
    db.commit()
    row, lines = get_inquiry(db, row.id)
    return inquiry_to_dict(row, lines)


@router.put("/inquiries/{iid}")
def api_update_inquiry(
    iid: int, body: InquiryIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        update_inquiry(db, iid, body.model_dump(), user=principal.username)
        db.commit()
        row, lines = get_inquiry(db, iid)
        return inquiry_to_dict(row, lines)
    except ValueError as exc:
        raise _err(exc) from exc


@router.post("/inquiries/{iid}/to-quote")
def api_inquiry_to_quote(
    iid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        quote = create_quote_from_inquiry(db, iid, user=principal.username)
        db.commit()
        return {"quote_id": quote.id, "quote_no": quote.quote_no}
    except ValueError as exc:
        raise _err(exc) from exc


# —— 设计/打样 ——


@router.get("/designs")
def api_list_designs(
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_presales),
):
    return {"items": [design_to_dict(r) for r in list_designs(db, q=q, status=status)]}


@router.post("/designs")
def api_create_design(
    body: DesignIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    row = create_design(db, body.model_dump(), user=principal.username)
    db.commit()
    db.refresh(row)
    return design_to_dict(row)


@router.put("/designs/{did}")
def api_update_design(
    did: int, body: DesignIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        row = update_design(db, did, body.model_dump(exclude_unset=True), user=principal.username)
        db.commit()
        db.refresh(row)
        return design_to_dict(row)
    except ValueError as exc:
        raise _err(exc) from exc


@router.post("/quotes/{qid}/to-design")
def api_quote_to_design(
    qid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        row = create_design_from_quote(db, qid, user=principal.username)
        db.commit()
        db.refresh(row)
        return design_to_dict(row)
    except ValueError as exc:
        raise _err(exc) from exc


@router.post("/quotes/{qid}/to-sample-order")
def api_quote_to_sample(
    qid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        row = create_sample_order_from_quote(db, qid, user=principal.username)
        db.commit()
        db.refresh(row)
        return sample_order_to_dict(row)
    except ValueError as exc:
        raise _err(exc) from exc


@router.post("/quotes/{qid}/to-sales-order")
def api_quote_to_sales(
    qid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        so = create_sales_order_from_quote(db, qid, user=principal.username)
        db.commit()
        lines = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.so_id == so.id).all()
        return sales_order_to_dict(so, lines)
    except ValueError as exc:
        raise _err(exc) from exc


@router.patch("/quotes/{qid}/presales-fields")
def api_patch_quote_presales(
    qid: int, body: QuoteLinkIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    q = db.query(QuoteOrder).filter(QuoteOrder.id == qid).first()
    if not q:
        raise HTTPException(status_code=404, detail="报价单不存在")
    q.supplier_name = (body.supplier_name or "").strip()
    q.supplier_cost = float(body.supplier_cost or 0)
    q.sell_price = float(body.sell_price or 0)
    q.quote_kind = (body.quote_kind or "cost").strip()
    if body.inquiry_id is not None:
        q.inquiry_id = body.inquiry_id
    if body.customer_id is not None:
        q.customer_id = body.customer_id
    q.updated_by = principal.username
    db.commit()
    return {
        "id": q.id,
        "quote_no": q.quote_no,
        "inquiry_id": q.inquiry_id,
        "supplier_name": q.supplier_name,
        "supplier_cost": q.supplier_cost,
        "sell_price": q.sell_price,
        "quote_kind": q.quote_kind,
    }


# —— 打样订单 / 销售订单列表 ——


@router.get("/sample-orders")
def api_list_sample_orders(
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_presales),
):
    return {"items": [sample_order_to_dict(r) for r in list_sample_orders(db, q=q, status=status)]}


@router.post("/sample-orders")
def api_create_sample_order(
    body: SampleOrderIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    row = create_sample_order(db, body.model_dump(), user=principal.username)
    db.commit()
    db.refresh(row)
    return sample_order_to_dict(row)


@router.get("/sales-orders")
def api_list_sales_orders(
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_presales),
):
    items = []
    for r in list_sales_orders(db, q=q, status=status):
        lines = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.so_id == r.id).all()
        items.append(sales_order_to_dict(r, lines))
    return {"items": items}


# —— 样品邮寄 ——


@router.get("/sample-mails")
def api_list_mails(
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_presales),
):
    return {"items": [mail_to_dict(r) for r in list_mails(db, q=q, status=status)]}


@router.post("/sample-mails")
def api_create_mail(body: MailIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)):
    row = create_mail(db, body.model_dump(), user=principal.username)
    db.commit()
    db.refresh(row)
    return mail_to_dict(row)


@router.put("/sample-mails/{mid}")
def api_update_mail(
    mid: int, body: MailIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        row = update_mail(db, mid, body.model_dump(exclude_unset=True), user=principal.username)
        db.commit()
        db.refresh(row)
        return mail_to_dict(row)
    except ValueError as exc:
        raise _err(exc) from exc


# —— 借样 ——


@router.get("/sample-loans")
def api_list_loans(
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_presales),
):
    return {"items": [loan_to_dict(r) for r in list_loans(db, q=q, status=status)]}


@router.post("/sample-loans")
def api_create_loan(body: LoanIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)):
    row = create_loan(db, body.model_dump(), user=principal.username)
    db.commit()
    db.refresh(row)
    return loan_to_dict(row)


@router.put("/sample-loans/{lid}")
def api_update_loan(
    lid: int, body: LoanIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_presales)
):
    try:
        row = update_loan(db, lid, body.model_dump(exclude_unset=True), user=principal.username)
        db.commit()
        db.refresh(row)
        return loan_to_dict(row)
    except ValueError as exc:
        raise _err(exc) from exc
