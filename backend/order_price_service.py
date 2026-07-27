"""订单行含税单价缓存：避免结案删除后出货金额漏计。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from models import OrderLinePrice, ReceiveQtyEvent, SrmOrder

logger = logging.getLogger(__name__)

BOARD_PRICE_CUSTOMERS = ("feilisi", "enjiu", "yonglian")


def compute_unit_price(
    *,
    tax_amount: float = 0,
    batch_pur_qty: float = 0,
    tax_price: float = 0,
) -> float:
    """优先 taxPrice；否则 tax_amount / batch_pur_qty。"""
    if float(tax_price or 0) > 0:
        return float(tax_price)
    qty = float(batch_pur_qty or 0)
    if qty > 0:
        return float(tax_amount or 0) / qty
    return 0.0


def upsert_line_price(
    db: Session,
    *,
    line_key: str,
    customer_id: str,
    purchase_no: Optional[str] = None,
    product_goods_no: Optional[str] = None,
    tax_amount: float = 0,
    batch_pur_qty: float = 0,
    tax_price: float = 0,
    source: str = "",
) -> Optional[OrderLinePrice]:
    key = (line_key or "").strip()
    if not key:
        return None
    unit = compute_unit_price(
        tax_amount=tax_amount, batch_pur_qty=batch_pur_qty, tax_price=tax_price
    )
    if unit <= 0:
        return None
    row = db.query(OrderLinePrice).filter(OrderLinePrice.line_key == key).first()
    if row is None:
        # 同事务内已 pending insert 时 query 可能看不到，避免 UNIQUE 冲突
        for obj in list(db.new):
            if isinstance(obj, OrderLinePrice) and obj.line_key == key:
                row = obj
                break
    now = datetime.utcnow()
    if row:
        row.customer_id = customer_id
        row.purchase_no = purchase_no or row.purchase_no
        row.product_goods_no = product_goods_no or row.product_goods_no
        row.tax_amount = float(tax_amount or 0)
        row.batch_pur_qty = float(batch_pur_qty or 0)
        row.unit_price = unit
        row.source = source or row.source
        row.updated_at = now
        return row
    row = OrderLinePrice(
        line_key=key,
        customer_id=customer_id,
        purchase_no=purchase_no,
        product_goods_no=product_goods_no,
        tax_amount=float(tax_amount or 0),
        batch_pur_qty=float(batch_pur_qty or 0),
        unit_price=unit,
        source=source or "",
        updated_at=now,
    )
    db.add(row)
    return row


def upsert_from_order(db: Session, order: SrmOrder, source: str = "srm_order") -> None:
    upsert_line_price(
        db,
        line_key=order.line_key,
        customer_id=order.customer_id,
        purchase_no=order.purchase_no,
        product_goods_no=order.product_goods_no,
        tax_amount=float(order.tax_amount or 0),
        batch_pur_qty=float(order.batch_pur_qty or 0),
        source=source,
    )


def upsert_from_order_data(db: Session, order_data: dict, source: str = "srm_sync") -> None:
    upsert_line_price(
        db,
        line_key=str(order_data.get("line_key") or ""),
        customer_id=str(order_data.get("customer_id") or ""),
        purchase_no=order_data.get("purchase_no"),
        product_goods_no=order_data.get("product_goods_no"),
        tax_amount=float(order_data.get("tax_amount") or 0),
        batch_pur_qty=float(order_data.get("batch_pur_qty") or 0),
        tax_price=float(order_data.get("tax_price") or 0),
        source=source,
    )


def seed_prices_from_orders(db: Session, customer_ids: Optional[Iterable[str]] = None) -> int:
    q = db.query(SrmOrder)
    if customer_ids:
        q = q.filter(SrmOrder.customer_id.in_(list(customer_ids)))
    n = 0
    for order in q.all():
        if upsert_line_price(
            db,
            line_key=order.line_key,
            customer_id=order.customer_id,
            purchase_no=order.purchase_no,
            product_goods_no=order.product_goods_no,
            tax_amount=float(order.tax_amount or 0),
            batch_pur_qty=float(order.batch_pur_qty or 0),
            source="seed_order",
        ):
            n += 1
    return n


def unit_price_map(db: Session, customer_ids: Optional[Iterable[str]] = None) -> dict[str, float]:
    """看板金额用：缓存 + 当前订单合并（订单可覆盖刷新）。"""
    ids = list(customer_ids or BOARD_PRICE_CUSTOMERS)
    out: dict[str, float] = {}
    for row in (
        db.query(OrderLinePrice)
        .filter(OrderLinePrice.customer_id.in_(ids), OrderLinePrice.unit_price > 0)
        .all()
    ):
        out[row.line_key] = float(row.unit_price)
    for order in db.query(SrmOrder).filter(SrmOrder.customer_id.in_(ids)).all():
        key = (order.line_key or "").strip()
        qty = float(order.batch_pur_qty or 0)
        if not key or qty <= 0:
            continue
        unit = float(order.tax_amount or 0) / qty
        if unit > 0:
            out[key] = unit
    return out


def _event_date_window() -> tuple[str, str]:
    from receive_events import board_history_start
    from receive_snapshot import today_shanghai

    return board_history_start().isoformat(), today_shanghai().isoformat()


def _missing_purchase_nos(db: Session, customer_id: str, priced_keys: set[str]) -> set[str]:
    start, end = _event_date_window()
    events = (
        db.query(ReceiveQtyEvent)
        .filter(
            ReceiveQtyEvent.customer_id == customer_id,
            ReceiveQtyEvent.event_date >= start,
            ReceiveQtyEvent.event_date <= end,
            ReceiveQtyEvent.qty > 0,
        )
        .all()
    )
    missing: set[str] = set()
    for ev in events:
        key = (ev.line_key or "").strip()
        if not key or key in priced_keys:
            continue
        parts = key.split("|")
        if len(parts) >= 2 and parts[1]:
            missing.add(parts[1])
    return missing


def _priced_keys(db: Session, customer_id: str) -> set[str]:
    keys = {
        r.line_key
        for r in db.query(OrderLinePrice.line_key)
        .filter(OrderLinePrice.customer_id == customer_id, OrderLinePrice.unit_price > 0)
        .all()
    }
    for (key,) in db.query(SrmOrder.line_key).filter(SrmOrder.customer_id == customer_id).all():
        if key:
            keys.add(key)
    return keys


async def backfill_feilisi_prices(db: Session) -> int:
    from config import get_enabled_customers
    from srm_client import SrmClient, _normalize_seq, make_line_key

    priced = _priced_keys(db, "feilisi")
    missing_pos = _missing_purchase_nos(db, "feilisi", priced)
    if not missing_pos:
        return 0

    customer = next((c for c in get_enabled_customers() if c["id"] == "feilisi"), None)
    if not customer:
        return 0
    client = SrmClient(customer)
    await client.login()
    written = 0
    for i, po in enumerate(sorted(missing_pos)):
        try:
            body = await client.fetch_purchase_body_lines(po)
        except Exception as exc:
            logger.warning("菲利斯回补单价失败 %s: %s", po, exc)
            continue
        for line in body or []:
            seq = _normalize_seq(line.get("purchaseSeq"), width=4)
            phase = _normalize_seq(line.get("purchasePhaseSeq"))
            key = make_line_key("feilisi", po, seq, phase)
            row = upsert_line_price(
                db,
                line_key=key,
                customer_id="feilisi",
                purchase_no=po,
                product_goods_no=(line.get("goodsNo") or line.get("itemNo") or None),
                tax_amount=float(line.get("taxAmount") or 0),
                batch_pur_qty=float(line.get("batchPurQty") or line.get("purchaseQty") or 0),
                tax_price=float(line.get("taxPrice") or 0),
                source="srm_purchase_body",
            )
            if row:
                written += 1
        if (i + 1) % 20 == 0:
            db.commit()
            logger.info("菲利斯单价回补进度 %s/%s", i + 1, len(missing_pos))
    db.commit()
    logger.info("菲利斯单价回补写入 %s 行（缺 PO %s）", written, len(missing_pos))
    return written


async def backfill_enjiu_prices(db: Session) -> int:
    from config import get_enabled_customers
    from receive_events import board_history_start
    from srm_client import make_line_key
    from srm_client_v2 import SrmClientV2
    from srm_sync import _pick, _v2_line_phase

    priced = _priced_keys(db, "enjiu")
    missing_pos = _missing_purchase_nos(db, "enjiu", priced)
    if not missing_pos:
        return 0

    customer = next((c for c in get_enabled_customers() if c["id"] == "enjiu"), None)
    if not customer:
        return 0
    client = SrmClientV2(customer)
    written = 0
    try:
        await client.login()
        date_from = board_history_start().isoformat()
        lines: list[dict] = []
        for closed, df in ((False, date_from), (True, date_from), (True, "")):
            try:
                part = await client.fetch_body_detail_list(closed=closed, date_from=df)
                lines.extend(part or [])
            except Exception as exc:
                logger.warning(
                    "恩玖拉取%s订单失败(date_from=%s): %s",
                    "结案" if closed else "进行中",
                    df or "空",
                    exc,
                )

        seen: set[str] = set()
        for line in lines:
            purchase_no = str(_pick(line, "purchaseNo", "purchase_no") or "").strip()
            if not purchase_no:
                continue
            seq = str(_pick(line, "purchaseSeq", "purchase_seq", "lineNo", "seq") or "0")
            phase = _v2_line_phase(line)
            key = make_line_key("enjiu", purchase_no, seq, phase)
            if key in seen:
                continue
            seen.add(key)
            tax = float(_pick(line, "transCurrTaxAmount", "taxAmount", "tax_amount", default=0) or 0)
            qty = float(
                _pick(line, "purchaseQty", "batchPurQty", "batch_pur_qty", "qty", default=0) or 0
            )
            tax_price = float(_pick(line, "taxPrice", "transCurrTaxPrice", default=0) or 0)
            row = upsert_line_price(
                db,
                line_key=key,
                customer_id="enjiu",
                purchase_no=purchase_no,
                product_goods_no=_pick(line, "itemNo", "goodsNo", "product_goods_no"),
                tax_amount=tax,
                batch_pur_qty=qty,
                tax_price=tax_price,
                source="srm_v2_body",
            )
            if row and purchase_no in missing_pos:
                written += 1
    finally:
        await client.close()
    db.commit()
    logger.info("恩玖单价回补写入 %s 行（缺 PO %s）", written, len(missing_pos))
    return written


async def backfill_board_prices(db: Session) -> dict[str, int]:
    seed_prices_from_orders(db, BOARD_PRICE_CUSTOMERS)
    db.commit()
    feilisi_n = await backfill_feilisi_prices(db)
    enjiu_n = await backfill_enjiu_prices(db)
    yonglian_n = seed_prices_from_orders(db, ("yonglian",))
    db.commit()
    return {"feilisi": feilisi_n, "enjiu": enjiu_n, "yonglian": yonglian_n}
