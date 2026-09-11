"""售前闭环服务：询价 / 打样 / 样品邮寄 / 借样 / 报价转单"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import (
    ErpSalesOrder,
    ErpSalesOrderLine,
    PresalesInquiry,
    PresalesInquiryLine,
    QuoteOrder,
    SampleDesign,
    SampleLoan,
    SampleMail,
    SampleOrder,
)
from sales_service import sample_order_to_dict as sample_order_to_dict  # noqa: F401 — re-export
from sales_service import sales_order_to_dict as sales_order_to_dict  # noqa: F401 — re-export


def _now() -> datetime:
    return datetime.utcnow()


def _touch(row: Any, user: str = "") -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()
    if user and hasattr(row, "updated_by"):
        row.updated_by = user


# —— 询价单 ——


def inquiry_to_dict(row: PresalesInquiry, lines: list[PresalesInquiryLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "inquiry_no": row.inquiry_no,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name or "",
        "contact": row.contact or "",
        "phone": row.phone or "",
        "title": row.title or "",
        "status": row.status,
        "remark": row.remark or "",
        "created_by": row.created_by or "",
        "updated_by": row.updated_by or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "sort_order": ln.sort_order,
                "material_code": ln.material_code,
                "material_name": ln.material_name,
                "spec": ln.spec,
                "qty": ln.qty,
                "unit": ln.unit,
                "remark": ln.remark,
            }
            for ln in lines
        ]
    return d


def list_inquiries(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[PresalesInquiry]:
    query = db.query(PresalesInquiry)
    if status.strip():
        query = query.filter(PresalesInquiry.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                PresalesInquiry.inquiry_no.like(like),
                PresalesInquiry.customer_name.like(like),
                PresalesInquiry.title.like(like),
            )
        )
    return query.order_by(PresalesInquiry.id.desc()).limit(limit).all()


def get_inquiry(db: Session, iid: int) -> tuple[PresalesInquiry, list[PresalesInquiryLine]]:
    row = db.query(PresalesInquiry).filter(PresalesInquiry.id == iid).first()
    if not row:
        raise ValueError("询价单不存在")
    lines = (
        db.query(PresalesInquiryLine)
        .filter(PresalesInquiryLine.inquiry_id == iid)
        .order_by(PresalesInquiryLine.sort_order, PresalesInquiryLine.id)
        .all()
    )
    return row, lines


def create_inquiry(db: Session, data: dict, *, user: str) -> PresalesInquiry:
    row = PresalesInquiry(
        inquiry_no=next_doc_number(db, "inquiry"),
        customer_id=data.get("customer_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        contact=(data.get("contact") or "").strip(),
        phone=(data.get("phone") or "").strip(),
        title=(data.get("title") or "").strip() or "客户询价",
        status="draft",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
        updated_by=user,
    )
    db.add(row)
    db.flush()
    for i, ln in enumerate(data.get("lines") or []):
        db.add(
            PresalesInquiryLine(
                inquiry_id=row.id,
                sort_order=i,
                material_code=(ln.get("material_code") or "").strip(),
                material_name=(ln.get("material_name") or "").strip(),
                spec=(ln.get("spec") or "").strip(),
                qty=float(ln.get("qty") or 0),
                unit=(ln.get("unit") or "PCS").strip(),
                remark=(ln.get("remark") or "").strip(),
            )
        )
    return row


def update_inquiry(db: Session, iid: int, data: dict, *, user: str) -> PresalesInquiry:
    row, _ = get_inquiry(db, iid)
    if row.status in ("closed", "void"):
        raise ValueError("已关闭/作废的询价单不可改")
    for k in ("customer_id",):
        if k in data:
            setattr(row, k, data.get(k))
    for k in ("customer_name", "contact", "phone", "title", "remark"):
        if k in data and data[k] is not None:
            setattr(row, k, str(data[k]).strip())
    if "status" in data and data["status"]:
        row.status = str(data["status"]).strip()
    if "lines" in data and data["lines"] is not None:
        db.query(PresalesInquiryLine).filter(PresalesInquiryLine.inquiry_id == iid).delete()
        for i, ln in enumerate(data["lines"] or []):
            db.add(
                PresalesInquiryLine(
                    inquiry_id=row.id,
                    sort_order=i,
                    material_code=(ln.get("material_code") or "").strip(),
                    material_name=(ln.get("material_name") or "").strip(),
                    spec=(ln.get("spec") or "").strip(),
                    qty=float(ln.get("qty") or 0),
                    unit=(ln.get("unit") or "PCS").strip(),
                    remark=(ln.get("remark") or "").strip(),
                )
            )
    _touch(row, user)
    return row


def create_quote_from_inquiry(db: Session, iid: int, *, user: str) -> QuoteOrder:
    from quotation_service import create_quote

    row, lines = get_inquiry(db, iid)
    first = lines[0] if lines else None
    quote = create_quote(
        db,
        customer_name=row.customer_name,
        product_name=(first.material_name if first else row.title) or "",
        product_code=(first.material_code if first else "") or "",
        remark=f"来源询价单 {row.inquiry_no}",
        batch_qty=float(first.qty) if first else 0,
        username=user,
    )
    quote.inquiry_id = row.id
    quote.customer_id = row.customer_id
    quote.quote_kind = "cost"
    if row.status == "draft":
        row.status = "quoting"
    _touch(row, user)
    db.flush()
    return quote


# —— 设计/打样任务 ——


def design_to_dict(row: SampleDesign) -> dict:
    return {
        "id": row.id,
        "design_no": row.design_no,
        "inquiry_id": row.inquiry_id,
        "quote_id": row.quote_id,
        "customer_name": row.customer_name,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "status": row.status,
        "owner": row.owner,
        "remark": row.remark,
        "confirmed_at": row.confirmed_at,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_designs(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[SampleDesign]:
    query = db.query(SampleDesign)
    if status.strip():
        query = query.filter(SampleDesign.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                SampleDesign.design_no.like(like),
                SampleDesign.customer_name.like(like),
                SampleDesign.product_code.like(like),
                SampleDesign.product_name.like(like),
            )
        )
    return query.order_by(SampleDesign.id.desc()).limit(limit).all()


def create_design(db: Session, data: dict, *, user: str) -> SampleDesign:
    # 设计任务单号：SJ + 日期流水（复用 sample_order 序列后改前缀）
    raw = next_doc_number(db, "sample_order")
    design_no = ("SJ" + raw[2:]) if raw.startswith("DY") else raw
    row = SampleDesign(
        design_no=design_no,
        inquiry_id=data.get("inquiry_id"),
        quote_id=data.get("quote_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        product_code=(data.get("product_code") or "").strip(),
        product_name=(data.get("product_name") or "").strip(),
        status=(data.get("status") or "draft").strip(),
        owner=(data.get("owner") or user).strip(),
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def update_design(db: Session, did: int, data: dict, *, user: str) -> SampleDesign:
    row = db.query(SampleDesign).filter(SampleDesign.id == did).first()
    if not row:
        raise ValueError("设计/打样任务不存在")
    for k in ("customer_name", "product_code", "product_name", "owner", "remark", "status"):
        if k in data and data[k] is not None:
            setattr(row, k, str(data[k]).strip())
    if data.get("status") == "confirmed" and not row.confirmed_at:
        row.confirmed_at = _now()
    _touch(row, user)
    return row


def create_design_from_quote(db: Session, quote_id: int, *, user: str) -> SampleDesign:
    q = db.query(QuoteOrder).filter(QuoteOrder.id == quote_id).first()
    if not q:
        raise ValueError("报价单不存在")
    if q.status != "confirmed":
        raise ValueError("仅已确认报价可下推设计/打样")
    return create_design(
        db,
        {
            "inquiry_id": q.inquiry_id,
            "quote_id": q.id,
            "customer_name": q.customer_name,
            "product_code": q.product_code,
            "product_name": q.product_name,
            "remark": f"来源报价 {q.quote_no}",
            "status": "designing",
        },
        user=user,
    )


# —— 打样订单 ——


def list_sample_orders(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[SampleOrder]:
    query = db.query(SampleOrder)
    if status.strip():
        query = query.filter(SampleOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                SampleOrder.sample_no.like(like),
                SampleOrder.customer_name.like(like),
                SampleOrder.product_code.like(like),
            )
        )
    return query.order_by(SampleOrder.id.desc()).limit(limit).all()


def create_sample_order(db: Session, data: dict, *, user: str) -> SampleOrder:
    row = SampleOrder(
        sample_no=next_doc_number(db, "sample_order"),
        inquiry_id=data.get("inquiry_id"),
        quote_id=data.get("quote_id"),
        design_id=data.get("design_id"),
        customer_id=data.get("customer_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        product_code=(data.get("product_code") or "").strip(),
        product_name=(data.get("product_name") or "").strip(),
        qty=float(data.get("qty") or 0),
        unit=(data.get("unit") or "PCS").strip() or "PCS",
        unit_price=float(data.get("unit_price") or 0),
        due_date=(data.get("due_date") or "").strip(),
        sample_attr=(data.get("sample_attr") or "new_product").strip() or "new_product",
        bom_model_id=data.get("bom_model_id"),
        status=(data.get("status") or "draft").strip(),
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def create_sample_order_from_quote(db: Session, quote_id: int, *, user: str) -> SampleOrder:
    q = db.query(QuoteOrder).filter(QuoteOrder.id == quote_id).first()
    if not q:
        raise ValueError("报价单不存在")
    if q.status != "confirmed":
        raise ValueError("仅已确认报价可转打样订单")
    return create_sample_order(
        db,
        {
            "inquiry_id": q.inquiry_id,
            "quote_id": q.id,
            "customer_id": q.customer_id,
            "customer_name": q.customer_name,
            "product_code": q.product_code,
            "product_name": q.product_name,
            "qty": q.batch_qty or 1,
            "unit_price": float(q.sell_price or q.unit_price or 0),
            "status": "draft",
            "remark": f"来源报价 {q.quote_no}",
        },
        user=user,
    )


# —— 销售订单草稿 ——


def list_sales_orders(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[ErpSalesOrder]:
    query = db.query(ErpSalesOrder)
    if status.strip():
        query = query.filter(ErpSalesOrder.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(or_(ErpSalesOrder.so_no.like(like), ErpSalesOrder.customer_name.like(like)))
    return query.order_by(ErpSalesOrder.id.desc()).limit(limit).all()


def create_sales_order_from_quote(db: Session, quote_id: int, *, user: str) -> ErpSalesOrder:
    q = db.query(QuoteOrder).filter(QuoteOrder.id == quote_id).first()
    if not q:
        raise ValueError("报价单不存在")
    if q.status != "confirmed":
        raise ValueError("仅已确认报价可转销售订单")
    price = float(q.sell_price or q.unit_price or 0)
    qty = float(q.batch_qty or 1)
    so = ErpSalesOrder(
        so_no=next_doc_number(db, "sales_order"),
        order_kind="sales",
        inquiry_id=q.inquiry_id,
        quote_id=q.id,
        customer_id=q.customer_id,
        customer_name=q.customer_name or "",
        status="draft",
        remark=f"来源报价 {q.quote_no}",
        created_by=user,
    )
    db.add(so)
    db.flush()
    db.add(
        ErpSalesOrderLine(
            so_id=so.id,
            sort_order=0,
            material_code=q.product_code or "",
            material_name=q.product_name or "",
            qty=qty,
            unit="PCS",
            unit_price=price,
            amount=round(qty * price, 4),
        )
    )
    if q.inquiry_id:
        inq = db.query(PresalesInquiry).filter(PresalesInquiry.id == q.inquiry_id).first()
        if inq and inq.status not in ("closed", "void"):
            inq.status = "quoted"
            _touch(inq, user)
    db.flush()
    return so


# —— 样品邮寄 ——


def mail_to_dict(row: SampleMail) -> dict:
    return {
        "id": row.id,
        "mail_no": row.mail_no,
        "inquiry_id": row.inquiry_id,
        "customer_name": row.customer_name,
        "product_name": row.product_name,
        "channel": row.channel,
        "tracking_no": row.tracking_no,
        "link_url": row.link_url,
        "status": row.status,
        "sent_at": row.sent_at,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_mails(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[SampleMail]:
    query = db.query(SampleMail)
    if status.strip():
        query = query.filter(SampleMail.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(SampleMail.mail_no.like(like), SampleMail.customer_name.like(like), SampleMail.tracking_no.like(like))
        )
    return query.order_by(SampleMail.id.desc()).limit(limit).all()


def create_mail(db: Session, data: dict, *, user: str) -> SampleMail:
    raw = next_doc_number(db, "inquiry")
    mail_no = ("YP" + raw[2:]) if raw.startswith("XJ") else raw
    row = SampleMail(
        mail_no=mail_no,
        inquiry_id=data.get("inquiry_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        product_name=(data.get("product_name") or "").strip(),
        channel=(data.get("channel") or "mail").strip(),
        tracking_no=(data.get("tracking_no") or "").strip(),
        link_url=(data.get("link_url") or "").strip(),
        status=(data.get("status") or "draft").strip(),
        sent_at=(data.get("sent_at") or "").strip(),
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def update_mail(db: Session, mid: int, data: dict, *, user: str) -> SampleMail:
    row = db.query(SampleMail).filter(SampleMail.id == mid).first()
    if not row:
        raise ValueError("样品登记不存在")
    for k in ("customer_name", "product_name", "channel", "tracking_no", "link_url", "status", "sent_at", "remark"):
        if k in data and data[k] is not None:
            setattr(row, k, str(data[k]).strip())
    if "inquiry_id" in data:
        row.inquiry_id = data.get("inquiry_id")
    _touch(row, user)
    return row


# —— 借样单 ——


def loan_to_dict(row: SampleLoan) -> dict:
    return {
        "id": row.id,
        "loan_no": row.loan_no,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name,
        "product_code": row.product_code,
        "product_name": row.product_name,
        "qty": row.qty,
        "status": row.status,
        "lent_at": row.lent_at,
        "expect_return_at": row.expect_return_at,
        "returned_at": row.returned_at,
        "converted_so_id": row.converted_so_id,
        "remark": row.remark,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_loans(db: Session, *, q: str = "", status: str = "", limit: int = 200) -> list[SampleLoan]:
    query = db.query(SampleLoan)
    if status.strip():
        query = query.filter(SampleLoan.status == status.strip())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(SampleLoan.loan_no.like(like), SampleLoan.customer_name.like(like), SampleLoan.product_code.like(like))
        )
    return query.order_by(SampleLoan.id.desc()).limit(limit).all()


def create_loan(db: Session, data: dict, *, user: str) -> SampleLoan:
    row = SampleLoan(
        loan_no=next_doc_number(db, "sample_loan"),
        customer_id=data.get("customer_id"),
        customer_name=(data.get("customer_name") or "").strip(),
        product_code=(data.get("product_code") or "").strip(),
        product_name=(data.get("product_name") or "").strip(),
        qty=float(data.get("qty") or 1),
        status=(data.get("status") or "draft").strip(),
        lent_at=(data.get("lent_at") or "").strip(),
        expect_return_at=(data.get("expect_return_at") or "").strip(),
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    return row


def update_loan(db: Session, lid: int, data: dict, *, user: str) -> SampleLoan:
    row = db.query(SampleLoan).filter(SampleLoan.id == lid).first()
    if not row:
        raise ValueError("借样单不存在")
    for k in (
        "customer_name",
        "product_code",
        "product_name",
        "status",
        "lent_at",
        "expect_return_at",
        "returned_at",
        "remark",
    ):
        if k in data and data[k] is not None:
            setattr(row, k, str(data[k]).strip())
    if "customer_id" in data:
        row.customer_id = data.get("customer_id")
    if "qty" in data and data["qty"] is not None:
        row.qty = float(data["qty"])
    # 借出快捷
    if data.get("status") == "lent" and not row.lent_at:
        row.lent_at = _now().strftime("%Y-%m-%d")
    if data.get("status") == "returned" and not row.returned_at:
        row.returned_at = _now().strftime("%Y-%m-%d")
    _touch(row, user)
    return row
