"""订单业务类型（开发桩）。"""
from __future__ import annotations

from typing import Any, MutableMapping

BIZ_KIND_LABELS = {
    "pcba": "PCBA",
    "smt": "SMT",
    "other": "其他",
}


def apply_biz_kind(order_data: MutableMapping[str, Any]) -> None:
    if not isinstance(order_data, dict):
        return
    kind = (order_data.get("biz_kind") or order_data.get("order_type") or "other").strip().lower()
    order_data["biz_kind"] = kind or "other"
    order_data["biz_kind_label"] = BIZ_KIND_LABELS.get(kind, kind or "其他")
