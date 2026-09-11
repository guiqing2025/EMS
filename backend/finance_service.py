"""阶段9：应付/应收统计核销、付款申请审批、收款、出纳账户流水、发票/票据简版"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    ApPayableStub,
    ArReceivableStub,
    CashAccount,
    CashLedger,
    FinBill,
    InvoiceReg,
    PaymentDoc,
    PaymentRequest,
    PaymentRequestLine,
    ReceiptDoc,
    ReceiptDocLine,
)


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _ap_open(row: ApPayableStub) -> float:
    return round(float(row.amount or 0) - float(getattr(row, "settled_amount", 0) or 0), 4)


def _ar_open(row: ArReceivableStub) -> float:
    return round(float(row.amount or 0) - float(getattr(row, "settled_amount", 0) or 0), 4)


def _sync_ap_status(row: ApPayableStub) -> None:
    open_amt = _ap_open(row)
    if open_amt <= 1e-6:
        row.status = "cleared"
        row.settled_amount = float(row.amount or 0)
    elif float(getattr(row, "settled_amount", 0) or 0) > 0:
        row.status = "partial"
    else:
        row.status = "pending"


def _sync_ar_status(row: ArReceivableStub) -> None:
    open_amt = _ar_open(row)
    if open_amt <= 1e-6:
        row.status = "cleared"
        row.settled_amount = float(row.amount or 0)
    elif float(getattr(row, "settled_amount", 0) or 0) > 0:
        row.status = "partial"
    else:
        row.status = "pending"


def ap_to_dict(row: ApPayableStub) -> dict:
    settled = float(getattr(row, "settled_amount", 0) or 0)
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_no": row.source_no,
        "supplier_name": row.supplier_name,
        "amount": row.amount,
        "settled_amount": settled,
        "open_amount": round(float(row.amount or 0) - settled, 4),
        "status": row.status,
        "remark": row.remark or "",
        "created_at": row.created_at,
    }


def ar_to_dict(row: ArReceivableStub) -> dict:
    settled = float(getattr(row, "settled_amount", 0) or 0)
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_no": row.source_no,
        "customer_name": row.customer_name,
        "amount": row.amount,
        "settled_amount": settled,
        "open_amount": round(float(row.amount or 0) - settled, 4),
        "status": row.status,
        "remark": row.remark or "",
        "created_at": row.created_at,
    }


def list_ap(db: Session, *, status: str = "", limit: int = 200) -> list[ApPayableStub]:
    q = db.query(ApPayableStub)
    if status.strip():
        q = q.filter(ApPayableStub.status == status.strip())
    return q.order_by(ApPayableStub.id.desc()).limit(limit).all()


def list_ar(db: Session, *, status: str = "", limit: int = 200) -> list[ArReceivableStub]:
    q = db.query(ArReceivableStub)
    if status.strip():
        q = q.filter(ArReceivableStub.status == status.strip())
    return q.order_by(ArReceivableStub.id.desc()).limit(limit).all()


def ap_summary_by_supplier(db: Session) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"supplier_name": "", "amount": 0.0, "settled": 0.0, "open": 0.0, "count": 0})
    for row in list_ap(db, limit=2000):
        key = row.supplier_name or "(未填供应商)"
        b = buckets[key]
        b["supplier_name"] = key
        b["amount"] += float(row.amount or 0)
        b["settled"] += float(getattr(row, "settled_amount", 0) or 0)
        b["open"] += _ap_open(row)
        b["count"] += 1
    out = []
    for b in buckets.values():
        out.append(
            {
                "supplier_name": b["supplier_name"],
                "amount": round(b["amount"], 4),
                "settled_amount": round(b["settled"], 4),
                "open_amount": round(b["open"], 4),
                "count": b["count"],
            }
        )
    return sorted(out, key=lambda x: -x["open_amount"])


def ar_summary_by_customer(db: Session) -> list[dict]:
    buckets: dict[str, dict] = defaultdict(lambda: {"customer_name": "", "amount": 0.0, "settled": 0.0, "open": 0.0, "count": 0})
    for row in list_ar(db, limit=2000):
        key = row.customer_name or "(未填客户)"
        b = buckets[key]
        b["customer_name"] = key
        b["amount"] += float(row.amount or 0)
        b["settled"] += float(getattr(row, "settled_amount", 0) or 0)
        b["open"] += _ar_open(row)
        b["count"] += 1
    out = []
    for b in buckets.values():
        out.append(
            {
                "customer_name": b["customer_name"],
                "amount": round(b["amount"], 4),
                "settled_amount": round(b["settled"], 4),
                "open_amount": round(b["open"], 4),
                "count": b["count"],
            }
        )
    return sorted(out, key=lambda x: -x["open_amount"])


def create_other_expense(db: Session, data: dict, *, user: str) -> ApPayableStub:
    amt = float(data.get("amount") or 0)
    if amt <= 0:
        raise ValueError("金额须大于 0")
    source_no = next_doc_number(db, "other_expense")
    row = ApPayableStub(
        source_type="other_expense",
        source_id=0,
        source_no=source_no,
        supplier_name=(data.get("supplier_name") or data.get("counterparty") or "").strip(),
        amount=amt,
        settled_amount=0,
        status="pending",
        remark=(data.get("remark") or "其他费用支出").strip() or "其他费用支出",
    )
    db.add(row)
    db.flush()
    return row


def create_other_income(db: Session, data: dict, *, user: str) -> ArReceivableStub:
    amt = float(data.get("amount") or 0)
    if amt <= 0:
        raise ValueError("金额须大于 0")
    source_no = next_doc_number(db, "other_income")
    row = ArReceivableStub(
        source_type="other_income",
        source_id=0,
        source_no=source_no,
        customer_name=(data.get("customer_name") or data.get("counterparty") or "").strip(),
        amount=amt,
        settled_amount=0,
        status="pending",
        remark=(data.get("remark") or "其他费用收入").strip() or "其他费用收入",
    )
    db.add(row)
    db.flush()
    return row


# —— 出纳账户 ——


def ensure_default_accounts(db: Session) -> list[CashAccount]:
    defaults = [
        ("CASH", "库存现金", "cash", 0),
        ("BANK-MAIN", "基本户", "bank", 100000),
    ]
    out = []
    for code, name, kind, opening in defaults:
        row = db.query(CashAccount).filter(CashAccount.code == code).first()
        if not row:
            row = CashAccount(
                code=code,
                name=name,
                kind=kind,
                opening_balance=opening,
                balance=opening,
                is_active=True,
            )
            db.add(row)
            db.flush()
        out.append(row)
    return out


def account_to_dict(row: CashAccount) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "kind": row.kind,
        "opening_balance": row.opening_balance,
        "balance": row.balance,
        "is_active": bool(row.is_active),
        "remark": row.remark or "",
    }


def list_accounts(db: Session) -> list[CashAccount]:
    ensure_default_accounts(db)
    return db.query(CashAccount).filter(CashAccount.is_active.is_(True)).order_by(CashAccount.id).all()


def _post_ledger(
    db: Session,
    account: CashAccount,
    *,
    movement_type: str,
    amount: float,
    ref_type: str = "",
    ref_no: str = "",
    counterparty: str = "",
    remark: str = "",
    operator: str = "",
) -> CashLedger:
    """amount 正=收入，负=支出。"""
    if abs(amount) < 1e-9:
        raise ValueError("流水金额不能为 0")
    new_bal = round(float(account.balance or 0) + amount, 4)
    if amount < 0 and new_bal < -1e-6 and movement_type in ("payment", "transfer_out", "reimbursement"):
        raise ValueError(f"账户 {account.code} 余额不足（当前 {account.balance}）")
    account.balance = new_bal
    led = CashLedger(
        account_id=account.id,
        account_code=account.code,
        movement_type=movement_type,
        amount=amount,
        balance_after=new_bal,
        ref_type=ref_type,
        ref_no=ref_no,
        counterparty=counterparty,
        remark=remark,
        operator=operator,
    )
    db.add(led)
    db.flush()
    return led


def list_ledgers(db: Session, *, account_id: Optional[int] = None, limit: int = 200) -> list[CashLedger]:
    q = db.query(CashLedger)
    if account_id:
        q = q.filter(CashLedger.account_id == account_id)
    return q.order_by(CashLedger.id.desc()).limit(limit).all()


def ledger_to_dict(row: CashLedger) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "account_code": row.account_code,
        "movement_type": row.movement_type,
        "amount": row.amount,
        "balance_after": row.balance_after,
        "ref_type": row.ref_type,
        "ref_no": row.ref_no,
        "counterparty": row.counterparty,
        "remark": row.remark,
        "operator": row.operator,
        "created_at": row.created_at,
    }


def manual_entry(db: Session, data: dict, *, user: str) -> CashLedger:
    ensure_default_accounts(db)
    acc = db.query(CashAccount).filter(CashAccount.id == int(data.get("account_id") or 0)).first()
    if not acc:
        raise ValueError("账户不存在")
    amt = float(data.get("amount") or 0)
    return _post_ledger(
        db,
        acc,
        movement_type="manual",
        amount=amt,
        ref_type="manual",
        counterparty=(data.get("counterparty") or "").strip(),
        remark=(data.get("remark") or "手工录入").strip(),
        operator=user,
    )


def reimbursement(db: Session, data: dict, *, user: str) -> CashLedger:
    ensure_default_accounts(db)
    acc = db.query(CashAccount).filter(CashAccount.id == int(data.get("account_id") or 0)).first()
    if not acc:
        raise ValueError("账户不存在")
    amt = abs(float(data.get("amount") or 0))
    if amt <= 0:
        raise ValueError("报销金额须大于 0")
    return _post_ledger(
        db,
        acc,
        movement_type="reimbursement",
        amount=-amt,
        ref_type="reimbursement",
        counterparty=(data.get("payee") or "").strip(),
        remark=(data.get("remark") or "报销").strip(),
        operator=user,
    )


def transfer_accounts(db: Session, data: dict, *, user: str) -> tuple[CashLedger, CashLedger]:
    ensure_default_accounts(db)
    from_id = int(data.get("from_account_id") or 0)
    to_id = int(data.get("to_account_id") or 0)
    if from_id == to_id:
        raise ValueError("调拨账户不能相同")
    src = db.query(CashAccount).filter(CashAccount.id == from_id).first()
    dst = db.query(CashAccount).filter(CashAccount.id == to_id).first()
    if not src or not dst:
        raise ValueError("账户不存在")
    amt = abs(float(data.get("amount") or 0))
    if amt <= 0:
        raise ValueError("调拨金额须大于 0")
    out_led = _post_ledger(
        db,
        src,
        movement_type="transfer_out",
        amount=-amt,
        ref_type="transfer",
        ref_no=f"→{dst.code}",
        remark=(data.get("remark") or f"调拨至 {dst.code}").strip(),
        operator=user,
    )
    in_led = _post_ledger(
        db,
        dst,
        movement_type="transfer_in",
        amount=amt,
        ref_type="transfer",
        ref_no=f"←{src.code}",
        remark=(data.get("remark") or f"调拨自 {src.code}").strip(),
        operator=user,
    )
    return out_led, in_led


# —— 付款申请 / 审批 / 付款 ——


def payment_request_to_dict(row: PaymentRequest, lines: list[PaymentRequestLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "request_no": row.request_no,
        "supplier_name": row.supplier_name,
        "amount": row.amount,
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "approved_by": row.approved_by or "",
        "approved_at": row.approved_at,
        "payment_id": row.payment_id,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {"id": ln.id, "ap_id": ln.ap_id, "ap_source_no": ln.ap_source_no, "amount": ln.amount} for ln in lines
        ]
    return d


def get_payment_request(db: Session, rid: int) -> tuple[PaymentRequest, list[PaymentRequestLine]]:
    row = db.query(PaymentRequest).filter(PaymentRequest.id == rid).first()
    if not row:
        raise ValueError("付款申请不存在")
    lines = db.query(PaymentRequestLine).filter(PaymentRequestLine.request_id == rid).all()
    return row, lines


def list_payment_requests(db: Session, *, limit: int = 100) -> list[PaymentRequest]:
    return db.query(PaymentRequest).order_by(PaymentRequest.id.desc()).limit(limit).all()


def create_payment_request(db: Session, data: dict, *, user: str) -> PaymentRequest:
    ap_ids = data.get("ap_ids") or []
    if not ap_ids:
        raise ValueError("请选择应付明细")
    lines_data = []
    supplier = (data.get("supplier_name") or "").strip()
    total = 0.0
    for ap_id in ap_ids:
        ap = db.query(ApPayableStub).filter(ApPayableStub.id == int(ap_id)).first()
        if not ap:
            raise ValueError(f"应付#{ap_id} 不存在")
        open_amt = _ap_open(ap)
        if open_amt <= 0:
            raise ValueError(f"应付 {ap.source_no} 已结清")
        if not supplier:
            supplier = ap.supplier_name or ""
        lines_data.append((ap, open_amt))
        total += open_amt
    row = PaymentRequest(
        request_no=next_doc_number(db, "payment_request"),
        supplier_name=supplier,
        amount=round(total, 4),
        status="submitted",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for ap, amt in lines_data:
        db.add(PaymentRequestLine(request_id=row.id, ap_id=ap.id, ap_source_no=ap.source_no, amount=amt))
    db.flush()
    return row


def approve_payment_request(db: Session, rid: int, *, user: str, approve: bool = True) -> PaymentRequest:
    row, _ = get_payment_request(db, rid)
    if row.status != "submitted":
        raise ValueError(f"申请状态 {row.status} 不可审批")
    if approve:
        row.status = "approved"
        row.approved_by = user
        row.approved_at = _now()
    else:
        row.status = "rejected"
        row.approved_by = user
        row.approved_at = _now()
    _touch(row)
    db.flush()
    return row


def create_payment_from_request(db: Session, request_id: int, *, account_id: int, user: str) -> PaymentDoc:
    ensure_default_accounts(db)
    req, lines = get_payment_request(db, request_id)
    if req.status != "approved":
        raise ValueError("仅已审批付款申请可生成付款单")
    if req.payment_id:
        raise ValueError("该申请已生成付款单")
    acc = db.query(CashAccount).filter(CashAccount.id == account_id).first()
    if not acc:
        raise ValueError("付款账户不存在")
    doc = PaymentDoc(
        payment_no=next_doc_number(db, "payment"),
        request_id=req.id,
        request_no=req.request_no,
        account_id=acc.id,
        supplier_name=req.supplier_name,
        amount=req.amount,
        status="draft",
        created_by=user,
        remark=f"来源申请 {req.request_no}",
    )
    db.add(doc)
    db.flush()
    return doc


def post_payment(db: Session, payment_id: int, *, user: str) -> PaymentDoc:
    doc = db.query(PaymentDoc).filter(PaymentDoc.id == payment_id).first()
    if not doc:
        raise ValueError("付款单不存在")
    if doc.status != "draft":
        raise ValueError(f"付款单状态 {doc.status} 不可过账")
    if not doc.request_id:
        raise ValueError("付款单未关联申请")
    req, lines = get_payment_request(db, doc.request_id)
    acc = db.query(CashAccount).filter(CashAccount.id == doc.account_id).first()
    if not acc:
        raise ValueError("账户不存在")
    for ln in lines:
        ap = db.query(ApPayableStub).filter(ApPayableStub.id == ln.ap_id).first()
        if not ap:
            raise ValueError(f"应付#{ln.ap_id} 不存在")
        pay = float(ln.amount or 0)
        if pay > _ap_open(ap) + 1e-6:
            raise ValueError(f"应付 {ap.source_no} 可付余额不足")
        ap.settled_amount = round(float(getattr(ap, "settled_amount", 0) or 0) + pay, 4)
        _sync_ap_status(ap)
    _post_ledger(
        db,
        acc,
        movement_type="payment",
        amount=-float(doc.amount or 0),
        ref_type="payment",
        ref_no=doc.payment_no,
        counterparty=doc.supplier_name,
        remark=f"付款 {doc.payment_no}",
        operator=user,
    )
    doc.status = "posted"
    doc.posted_by = user
    doc.posted_at = _now()
    req.status = "paid"
    req.payment_id = doc.id
    _touch(req)
    db.flush()
    try:
        from gl_service import voucher_from_payment

        voucher_from_payment(
            db, payment_id=doc.id, payment_no=doc.payment_no, amount=float(doc.amount or 0), user=user
        )
    except Exception:
        pass
    return doc


def payment_to_dict(row: PaymentDoc) -> dict:
    return {
        "id": row.id,
        "payment_no": row.payment_no,
        "request_id": row.request_id,
        "request_no": row.request_no,
        "account_id": row.account_id,
        "supplier_name": row.supplier_name,
        "amount": row.amount,
        "status": row.status,
        "posted_at": row.posted_at,
        "created_at": row.created_at,
    }


def list_payments(db: Session, *, limit: int = 100) -> list[PaymentDoc]:
    return db.query(PaymentDoc).order_by(PaymentDoc.id.desc()).limit(limit).all()


# —— 收款 ——


def receipt_to_dict(row: ReceiptDoc, lines: list[ReceiptDocLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "receipt_no": row.receipt_no,
        "account_id": row.account_id,
        "customer_name": row.customer_name,
        "amount": row.amount,
        "status": row.status,
        "posted_at": row.posted_at,
        "created_at": row.created_at,
        "remark": row.remark or "",
    }
    if lines is not None:
        d["lines"] = [
            {"id": ln.id, "ar_id": ln.ar_id, "ar_source_no": ln.ar_source_no, "amount": ln.amount} for ln in lines
        ]
    return d


def get_receipt(db: Session, rid: int) -> tuple[ReceiptDoc, list[ReceiptDocLine]]:
    row = db.query(ReceiptDoc).filter(ReceiptDoc.id == rid).first()
    if not row:
        raise ValueError("收款单不存在")
    lines = db.query(ReceiptDocLine).filter(ReceiptDocLine.receipt_id == rid).all()
    return row, lines


def list_receipts(db: Session, *, limit: int = 100) -> list[ReceiptDoc]:
    return db.query(ReceiptDoc).order_by(ReceiptDoc.id.desc()).limit(limit).all()


def create_receipt(db: Session, data: dict, *, user: str) -> ReceiptDoc:
    ensure_default_accounts(db)
    ar_ids = data.get("ar_ids") or []
    if not ar_ids:
        raise ValueError("请选择应收明细")
    acc = db.query(CashAccount).filter(CashAccount.id == int(data.get("account_id") or 0)).first()
    if not acc:
        raise ValueError("收款账户不存在")
    customer = (data.get("customer_name") or "").strip()
    total = 0.0
    pairs = []
    for ar_id in ar_ids:
        ar = db.query(ArReceivableStub).filter(ArReceivableStub.id == int(ar_id)).first()
        if not ar:
            raise ValueError(f"应收#{ar_id} 不存在")
        open_amt = _ar_open(ar)
        if open_amt <= 0:
            raise ValueError(f"应收 {ar.source_no} 已结清")
        if not customer:
            customer = ar.customer_name or ""
        pairs.append((ar, open_amt))
        total += open_amt
    row = ReceiptDoc(
        receipt_no=next_doc_number(db, "receipt"),
        account_id=acc.id,
        customer_name=customer,
        amount=round(total, 4),
        status="draft",
        created_by=user,
        remark=(data.get("remark") or "").strip(),
    )
    db.add(row)
    db.flush()
    for ar, amt in pairs:
        db.add(ReceiptDocLine(receipt_id=row.id, ar_id=ar.id, ar_source_no=ar.source_no, amount=amt))
    db.flush()
    return row


def post_receipt(db: Session, receipt_id: int, *, user: str) -> ReceiptDoc:
    row, lines = get_receipt(db, receipt_id)
    if row.status != "draft":
        raise ValueError(f"收款单状态 {row.status} 不可过账")
    acc = db.query(CashAccount).filter(CashAccount.id == row.account_id).first()
    if not acc:
        raise ValueError("账户不存在")
    for ln in lines:
        ar = db.query(ArReceivableStub).filter(ArReceivableStub.id == ln.ar_id).first()
        if not ar:
            raise ValueError(f"应收#{ln.ar_id} 不存在")
        recv = float(ln.amount or 0)
        if recv > _ar_open(ar) + 1e-6:
            raise ValueError(f"应收 {ar.source_no} 可收余额不足")
        ar.settled_amount = round(float(getattr(ar, "settled_amount", 0) or 0) + recv, 4)
        _sync_ar_status(ar)
    _post_ledger(
        db,
        acc,
        movement_type="receipt",
        amount=float(row.amount or 0),
        ref_type="receipt",
        ref_no=row.receipt_no,
        counterparty=row.customer_name,
        remark=f"收款 {row.receipt_no}",
        operator=user,
    )
    row.status = "posted"
    row.posted_by = user
    row.posted_at = _now()
    db.flush()
    try:
        from gl_service import voucher_from_receipt

        voucher_from_receipt(
            db, receipt_id=row.id, receipt_no=row.receipt_no, amount=float(row.amount or 0), user=user
        )
    except Exception:
        pass
    return row


# —— 发票 / 票据 ——


def create_invoice(db: Session, data: dict, *, user: str) -> InvoiceReg:
    row = InvoiceReg(
        invoice_no=(data.get("invoice_no") or next_doc_number(db, "invoice_reg")).strip(),
        direction=(data.get("direction") or "in").strip() or "in",
        counterparty=(data.get("counterparty") or "").strip(),
        amount=float(data.get("amount") or 0),
        tax_amount=float(data.get("tax_amount") or 0),
        related_doc_no=(data.get("related_doc_no") or "").strip(),
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def list_invoices(db: Session, *, limit: int = 100) -> list[InvoiceReg]:
    return db.query(InvoiceReg).order_by(InvoiceReg.id.desc()).limit(limit).all()


def invoice_to_dict(row: InvoiceReg) -> dict:
    return {
        "id": row.id,
        "invoice_no": row.invoice_no,
        "direction": row.direction,
        "counterparty": row.counterparty,
        "amount": row.amount,
        "tax_amount": row.tax_amount,
        "related_doc_no": row.related_doc_no,
        "remark": row.remark,
        "created_at": row.created_at,
    }


def create_bill(db: Session, data: dict, *, user: str) -> FinBill:
    row = FinBill(
        bill_no=(data.get("bill_no") or next_doc_number(db, "fin_bill")).strip(),
        bill_kind=(data.get("bill_kind") or "receivable").strip(),
        counterparty=(data.get("counterparty") or "").strip(),
        amount=float(data.get("amount") or 0),
        due_date=(data.get("due_date") or "").strip(),
        status=(data.get("status") or "held").strip() or "held",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def list_bills(db: Session, *, limit: int = 100) -> list[FinBill]:
    return db.query(FinBill).order_by(FinBill.id.desc()).limit(limit).all()


def bill_to_dict(row: FinBill) -> dict:
    return {
        "id": row.id,
        "bill_no": row.bill_no,
        "bill_kind": row.bill_kind,
        "counterparty": row.counterparty,
        "amount": row.amount,
        "due_date": row.due_date,
        "status": row.status,
        "remark": row.remark,
        "created_at": row.created_at,
    }
