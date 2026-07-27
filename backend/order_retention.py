"""订单明细保留策略：仅保留近 N 年数据。"""

from datetime import date, datetime
from typing import Optional

ORDER_RETENTION_YEARS = 3


def retention_cutoff_date() -> date:
    today = date.today()
    year = today.year - ORDER_RETENTION_YEARS
    try:
        return date(year, today.month, today.day)
    except ValueError:
        return date(year, today.month, 28)


def retention_cutoff_str() -> str:
    return retention_cutoff_date().isoformat()


def parse_order_date(value) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def order_record_date(order_data: dict) -> Optional[date]:
    return parse_order_date(order_data.get("purchase_date") or order_data.get("doc_date"))


def is_within_retention(order_data: dict) -> bool:
    d = order_record_date(order_data)
    if d is None:
        return True
    return d >= retention_cutoff_date()
