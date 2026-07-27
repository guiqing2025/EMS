"""独立订单报价业务"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import QuoteBomLine, QuoteCostLine, QuoteOrder
from quotation_bom_parse import parse_quote_bom_bytes
from quote_engine import DEFAULT_RATES, classify_and_price


def _now() -> datetime:
    return datetime.utcnow()


def next_quote_no(db: Session) -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"QJ-{today}-"
    last = (
        db.query(QuoteOrder)
        .filter(QuoteOrder.quote_no.like(f"{prefix}%"))
        .order_by(QuoteOrder.id.desc())
        .first()
    )
    seq = 1
    if last and last.quote_no.startswith(prefix):
        try:
            seq = int(last.quote_no.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:03d}"


def create_quote(
    db: Session,
    *,
    customer_name: str = "",
    product_name: str = "",
    product_code: str = "",
    remark: str = "",
    batch_qty: float = 0,
    username: str = "",
) -> QuoteOrder:
    row = QuoteOrder(
        quote_no=next_quote_no(db),
        customer_name=(customer_name or "").strip(),
        product_name=(product_name or "").strip(),
        product_code=(product_code or "").strip(),
        remark=(remark or "").strip() or None,
        batch_qty=float(batch_qty or 0),
        status="draft",
        created_by=username or None,
        updated_by=username or None,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def list_quotes(db: Session, *, keyword: str = "", status: str = "", limit: int = 100) -> list[QuoteOrder]:
    q = db.query(QuoteOrder).order_by(QuoteOrder.id.desc())
    if status:
        q = q.filter(QuoteOrder.status == status)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (QuoteOrder.quote_no.like(like))
            | (QuoteOrder.customer_name.like(like))
            | (QuoteOrder.product_code.like(like))
            | (QuoteOrder.product_name.like(like))
        )
    return q.limit(limit).all()


def get_quote(db: Session, quote_id: int) -> Optional[QuoteOrder]:
    return db.query(QuoteOrder).filter(QuoteOrder.id == quote_id).first()


def _replace_calc(db: Session, quote: QuoteOrder, result, *, filename: str = "", username: str = "") -> None:
    db.query(QuoteBomLine).filter(QuoteBomLine.quote_id == quote.id).delete()
    db.query(QuoteCostLine).filter(QuoteCostLine.quote_id == quote.id).delete()
    db.flush()

    for i, line in enumerate(result.bom_lines):
        db.add(
            QuoteBomLine(
                quote_id=quote.id,
                sort_order=i,
                seq=line.seq,
                material_code=line.material_code,
                material_name=line.material_name,
                spec=line.spec,
                qty_per=line.qty_per,
                unit=line.unit,
                position=line.position,
                package=line.package,
                bucket=line.bucket,
                ic_amount=line.ic_amount,
                dip_points=line.dip_points,
                calc_points=line.calc_points,
                calc_amount=line.calc_amount,
            )
        )
    for line in result.cost_lines:
        db.add(
            QuoteCostLine(
                quote_id=quote.id,
                sort_order=line.sort_order,
                section=line.section,
                item_key=line.item_key,
                item_name=line.item_name,
                qty=line.qty,
                points=line.points,
                unit_price=line.unit_price,
                unit=line.unit,
                amount=line.amount,
                note=line.note,
                editable=line.editable,
            )
        )

    quote.unit_price = result.unit_price
    quote.tooling_total = result.tooling_total
    quote.engineering_fee = result.engineering_fee
    batch = float(quote.batch_qty or 0)
    quote.grand_total = round(
        result.unit_price * batch + result.tooling_total + result.engineering_fee, 2
    ) if batch else round(result.unit_price + result.tooling_total + result.engineering_fee, 2)
    quote.status = "calculated"
    if filename:
        quote.source_filename = filename
    quote.updated_by = username or quote.updated_by
    quote.updated_at = _now()


def import_bom_and_calc(
    db: Session,
    quote_id: int,
    data: bytes,
    *,
    filename: str = "",
    username: str = "",
    tangxi: Optional[float] = None,
    stencil_qty: float = 1,
    wave_fixture_qty: float = 0,
) -> QuoteOrder:
    quote = get_quote(db, quote_id)
    if not quote:
        raise ValueError("报价单不存在")
    if quote.status == "void":
        raise ValueError("已作废报价单不可导入")

    bom_lines, meta = parse_quote_bom_bytes(data, filename)
    if not quote.product_code and meta.get("product_code"):
        quote.product_code = meta["product_code"]
    if not quote.product_name and meta.get("product_name"):
        quote.product_name = meta["product_name"]

    # 本单示例有波峰治具 30；默认导入不强制，由前端可改。若 DIP 点数>0 且未指定，给 0
    result = classify_and_price(
        bom_lines,
        tangxi=tangxi,
        stencil_qty=stencil_qty,
        wave_fixture_qty=wave_fixture_qty,
    )
    _replace_calc(db, quote, result, filename=filename, username=username)
    db.flush()
    return quote


def update_quote_header(
    db: Session,
    quote_id: int,
    *,
    customer_name: Optional[str] = None,
    product_name: Optional[str] = None,
    product_code: Optional[str] = None,
    remark: Optional[str] = None,
    batch_qty: Optional[float] = None,
    engineering_fee: Optional[float] = None,
    username: str = "",
) -> QuoteOrder:
    quote = get_quote(db, quote_id)
    if not quote:
        raise ValueError("报价单不存在")
    if customer_name is not None:
        quote.customer_name = customer_name.strip()
    if product_name is not None:
        quote.product_name = product_name.strip()
    if product_code is not None:
        quote.product_code = product_code.strip()
    if remark is not None:
        quote.remark = remark.strip() or None
    if batch_qty is not None:
        quote.batch_qty = float(batch_qty)
    if engineering_fee is not None:
        quote.engineering_fee = float(engineering_fee)
    batch = float(quote.batch_qty or 0)
    quote.grand_total = round(
        float(quote.unit_price or 0) * batch
        + float(quote.tooling_total or 0)
        + float(quote.engineering_fee or 0),
        2,
    )
    quote.updated_by = username or quote.updated_by
    quote.updated_at = _now()
    db.flush()
    return quote


def update_cost_lines(
    db: Session,
    quote_id: int,
    patches: list[dict[str, Any]],
    *,
    username: str = "",
) -> QuoteOrder:
    """按 item_key 更新可编辑费用行，并重算小计/单价。"""
    quote = get_quote(db, quote_id)
    if not quote:
        raise ValueError("报价单不存在")
    lines = db.query(QuoteCostLine).filter(QuoteCostLine.quote_id == quote_id).all()
    by_key = {x.item_key: x for x in lines}
    for p in patches:
        key = p.get("item_key")
        row = by_key.get(key)
        if not row:
            continue
        if "amount" in p and p["amount"] is not None:
            row.amount = float(p["amount"])
        if "qty" in p and p["qty"] is not None:
            row.qty = float(p["qty"])
            if row.unit_price and key in {"stencil", "wave_fixture", "bigpad"}:
                row.amount = round(row.qty * row.unit_price, 6)
        if "unit_price" in p and p["unit_price"] is not None:
            row.unit_price = float(p["unit_price"])
            if row.points:
                row.amount = round(row.points * row.unit_price, 6)
            elif row.qty:
                row.amount = round(row.qty * row.unit_price, 6)
        if "points" in p and p["points"] is not None:
            row.points = float(p["points"])
            if row.unit_price:
                row.amount = round(row.points * row.unit_price, 6)

    # 重算 SMT/DIP/治具小计与单价
    def amt(key: str) -> float:
        r = by_key.get(key)
        return float(r.amount or 0) if r else 0

    smt_keys = ["chip1", "chip2", "odd", "ic1", "ic2", "bigpad", "tangxi"]
    smt_sub = sum(amt(k) for k in smt_keys)
    if by_key.get("smt_subtotal"):
        by_key["smt_subtotal"].amount = round(smt_sub, 6)

    dip_sub = amt("dip2")
    if by_key.get("dip_subtotal"):
        by_key["dip_subtotal"].amount = round(dip_sub, 6)

    post_sub = 0.0
    for row in lines:
        if row.section == "post" and row.item_key != "post_subtotal":
            post_sub += float(row.amount or 0)
    if by_key.get("post_subtotal"):
        by_key["post_subtotal"].amount = round(post_sub, 6)
        post_sub = float(by_key["post_subtotal"].amount or 0)

    tooling = amt("stencil") + amt("wave_fixture")
    if by_key.get("tooling_subtotal"):
        by_key["tooling_subtotal"].amount = round(tooling, 6)

    unit_price = round(smt_sub + dip_sub + post_sub, 6)
    if by_key.get("unit_price"):
        by_key["unit_price"].amount = unit_price
        by_key["unit_price"].unit_price = unit_price

    quote.unit_price = unit_price
    quote.tooling_total = round(tooling, 6)
    batch = float(quote.batch_qty or 0)
    quote.grand_total = round(
        unit_price * batch + tooling + float(quote.engineering_fee or 0), 2
    ) if batch else round(unit_price + tooling + float(quote.engineering_fee or 0), 2)
    quote.updated_by = username or quote.updated_by
    quote.updated_at = _now()
    db.flush()
    return quote


def set_status(db: Session, quote_id: int, status: str, *, username: str = "") -> QuoteOrder:
    quote = get_quote(db, quote_id)
    if not quote:
        raise ValueError("报价单不存在")
    if status not in {"draft", "calculated", "confirmed", "void"}:
        raise ValueError("无效状态")
    quote.status = status
    quote.updated_by = username or quote.updated_by
    quote.updated_at = _now()
    db.flush()
    return quote


def delete_quote(db: Session, quote_id: int) -> None:
    """仅草稿/已作废可物理删除。"""
    quote = get_quote(db, quote_id)
    if not quote:
        raise ValueError("报价单不存在")
    if quote.status not in {"draft", "void"}:
        raise ValueError("仅草稿或已作废的报价单可删除，已核算/已确认请先作废")
    db.query(QuoteBomLine).filter(QuoteBomLine.quote_id == quote_id).delete()
    db.query(QuoteCostLine).filter(QuoteCostLine.quote_id == quote_id).delete()
    db.delete(quote)
    db.flush()


def quote_detail_dict(db: Session, quote: QuoteOrder) -> dict:
    bom = (
        db.query(QuoteBomLine)
        .filter(QuoteBomLine.quote_id == quote.id)
        .order_by(QuoteBomLine.sort_order, QuoteBomLine.id)
        .all()
    )
    costs = (
        db.query(QuoteCostLine)
        .filter(QuoteCostLine.quote_id == quote.id)
        .order_by(QuoteCostLine.sort_order, QuoteCostLine.id)
        .all()
    )
    return {
        "id": quote.id,
        "quote_no": quote.quote_no,
        "customer_name": quote.customer_name,
        "product_name": quote.product_name,
        "product_code": quote.product_code,
        "remark": quote.remark,
        "status": quote.status,
        "batch_qty": quote.batch_qty,
        "unit_price": quote.unit_price,
        "tooling_total": quote.tooling_total,
        "engineering_fee": quote.engineering_fee,
        "grand_total": quote.grand_total,
        "source_filename": quote.source_filename,
        "created_by": quote.created_by,
        "updated_by": quote.updated_by,
        "created_at": quote.created_at.isoformat() if quote.created_at else None,
        "updated_at": quote.updated_at.isoformat() if quote.updated_at else None,
        "rates": DEFAULT_RATES,
        "bom_lines": [
            {
                "id": x.id,
                "seq": x.seq,
                "material_code": x.material_code,
                "material_name": x.material_name,
                "spec": x.spec,
                "qty_per": x.qty_per,
                "unit": x.unit,
                "position": x.position,
                "package": x.package,
                "bucket": x.bucket,
                "ic_amount": x.ic_amount,
                "dip_points": x.dip_points,
                "calc_points": x.calc_points,
                "calc_amount": x.calc_amount,
            }
            for x in bom
        ],
        "cost_lines": [
            {
                "id": x.id,
                "section": x.section,
                "item_key": x.item_key,
                "item_name": x.item_name,
                "qty": x.qty,
                "points": x.points,
                "unit_price": x.unit_price,
                "unit": x.unit,
                "amount": x.amount,
                "note": x.note,
                "editable": x.editable,
            }
            for x in costs
        ],
    }
