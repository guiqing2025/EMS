"""新订单判定：客户下单日期在近 N 个自然日内。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

NEW_ORDER_DAYS = 3


def new_order_cutoff_date(today: Optional[date] = None) -> date:
    """含今天共 NEW_ORDER_DAYS 天，例如今天 7/18 → 从 7/16 起算。"""
    base = today or date.today()
    return base - timedelta(days=NEW_ORDER_DAYS - 1)


def new_order_date_from_str(today: Optional[date] = None) -> str:
    return new_order_cutoff_date(today).isoformat()


def parse_order_date(value: Optional[str]) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        return None
    head = text[:10].replace("/", "-")
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        pass
    digits = "".join(ch for ch in text if ch.isdigit())[:8]
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date()
        except ValueError:
            pass
    return None


def is_new_order(purchase_date: Optional[str], *, today: Optional[date] = None) -> bool:
    d = parse_order_date(purchase_date)
    if not d:
        return False
    return d >= new_order_cutoff_date(today)
