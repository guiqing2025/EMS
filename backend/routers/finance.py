"""财务 API：应付/应收、付款申请审批、收款、出纳、发票票据"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from finance_service import (
    account_to_dict,
    ap_summary_by_supplier,
    ap_to_dict,
    approve_payment_request,
    ar_summary_by_customer,
    ar_to_dict,
    bill_to_dict,
    create_bill,
    create_invoice,
    create_other_expense,
    create_other_income,
    create_payment_from_request,
    create_payment_request,
    create_receipt,
    ensure_default_accounts,
    get_payment_request,
    get_receipt,
    invoice_to_dict,
    ledger_to_dict,
    list_accounts,
    list_ap,
    list_ar,
    list_bills,
    list_invoices,
    list_ledgers,
    list_payment_requests,
    list_payments,
    list_receipts,
    manual_entry,
    payment_request_to_dict,
    payment_to_dict,
    post_payment,
    post_receipt,
    receipt_to_dict,
    reimbursement,
    transfer_accounts,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/finance",
    tags=["finance"],
    dependencies=[Depends(require_system_auth)],
)

FIN_ROLES = frozenset({"admin", "finance", "pmc"})


def require_fin(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in FIN_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无财务模块权限")


class IdsIn(BaseModel):
    ap_ids: list[int] = Field(default_factory=list)
    supplier_name: str = ""
    remark: str = ""


class ApproveIn(BaseModel):
    approve: bool = True


class PayFromReqIn(BaseModel):
    account_id: int


class ReceiptIn(BaseModel):
    account_id: int
    ar_ids: list[int] = Field(default_factory=list)
    customer_name: str = ""
    remark: str = ""


class OtherIn(BaseModel):
    amount: float
    supplier_name: str = ""
    customer_name: str = ""
    counterparty: str = ""
    remark: str = ""


class ManualIn(BaseModel):
    account_id: int
    amount: float
    counterparty: str = ""
    remark: str = ""


class ReimburseIn(BaseModel):
    account_id: int
    amount: float
    payee: str = ""
    remark: str = ""


class TransferIn(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: float
    remark: str = ""


class InvoiceIn(BaseModel):
    invoice_no: str = ""
    direction: str = "in"
    counterparty: str = ""
    amount: float = 0
    tax_amount: float = 0
    related_doc_no: str = ""
    remark: str = ""


class BillIn(BaseModel):
    bill_no: str = ""
    bill_kind: str = "receivable"
    counterparty: str = ""
    amount: float = 0
    due_date: str = ""
    remark: str = ""


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.get("/ap")
def api_ap(status: str = Query(""), db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [ap_to_dict(r) for r in list_ap(db, status=status)], "summary": ap_summary_by_supplier(db)}


@router.get("/ar")
def api_ar(status: str = Query(""), db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [ar_to_dict(r) for r in list_ar(db, status=status)], "summary": ar_summary_by_customer(db)}


@router.post("/ap/other-expense")
def api_oe(body: OtherIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_other_expense(db, _dump(body), user=principal.username)
        db.commit()
        return ap_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/ar/other-income")
def api_oi(body: OtherIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_other_income(db, _dump(body), user=principal.username)
        db.commit()
        return ar_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/payment-requests")
def api_list_pr(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    items = []
    for r in list_payment_requests(db):
        _, lines = get_payment_request(db, r.id)
        items.append(payment_request_to_dict(r, lines))
    return {"items": items}


@router.post("/payment-requests")
def api_create_pr(body: IdsIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_payment_request(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_payment_request(db, row.id)
        return payment_request_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/payment-requests/{rid}/approve")
def api_approve(rid: int, body: ApproveIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = approve_payment_request(db, rid, user=principal.username, approve=body.approve)
        db.commit()
        row, lines = get_payment_request(db, rid)
        return payment_request_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/payments/from-request/{request_id}")
def api_pay_from(request_id: int, body: PayFromReqIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        doc = create_payment_from_request(db, request_id, account_id=body.account_id, user=principal.username)
        db.commit()
        return payment_to_dict(doc)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/payments")
def api_list_pay(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [payment_to_dict(r) for r in list_payments(db)]}


@router.post("/payments/{pid}/post")
def api_post_pay(pid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        doc = post_payment(db, pid, user=principal.username)
        db.commit()
        return payment_to_dict(doc)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/receipts")
def api_list_rc(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    items = []
    for r in list_receipts(db):
        _, lines = get_receipt(db, r.id)
        items.append(receipt_to_dict(r, lines))
    return {"items": items}


@router.post("/receipts")
def api_create_rc(body: ReceiptIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_receipt(db, _dump(body), user=principal.username)
        db.commit()
        row, lines = get_receipt(db, row.id)
        return receipt_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/receipts/{rid}/post")
def api_post_rc(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = post_receipt(db, rid, user=principal.username)
        db.commit()
        row, lines = get_receipt(db, rid)
        return receipt_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/accounts")
def api_acc(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    ensure_default_accounts(db)
    db.commit()
    return {"items": [account_to_dict(r) for r in list_accounts(db)]}


@router.get("/ledgers")
def api_led(account_id: Optional[int] = None, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [ledger_to_dict(r) for r in list_ledgers(db, account_id=account_id)]}


@router.post("/cashier/manual")
def api_manual(body: ManualIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        led = manual_entry(db, _dump(body), user=principal.username)
        db.commit()
        return ledger_to_dict(led)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/cashier/reimbursement")
def api_reimb(body: ReimburseIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        led = reimbursement(db, _dump(body), user=principal.username)
        db.commit()
        return ledger_to_dict(led)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/cashier/transfer")
def api_xfer(body: TransferIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        out_led, in_led = transfer_accounts(db, _dump(body), user=principal.username)
        db.commit()
        return {"out": ledger_to_dict(out_led), "in": ledger_to_dict(in_led)}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/invoices")
def api_inv(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [invoice_to_dict(r) for r in list_invoices(db)]}


@router.post("/invoices")
def api_create_inv(body: InvoiceIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_invoice(db, _dump(body), user=principal.username)
        db.commit()
        return invoice_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/bills")
def api_bills(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_fin)):
    return {"items": [bill_to_dict(r) for r in list_bills(db)]}


@router.post("/bills")
def api_create_bill(body: BillIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_fin)):
    try:
        row = create_bill(db, _dump(body), user=principal.username)
        db.commit()
        return bill_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
