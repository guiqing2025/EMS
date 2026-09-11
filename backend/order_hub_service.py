"""订单中枢（开发桩）。"""
from __future__ import annotations

from typing import Any, Optional


def build_order_hub(db, purchase_no: str, **_kwargs) -> dict[str, Any]:
    return {
        "purchase_no": purchase_no or "",
        "status": "stub",
        "message": "order_hub_service 未包含在本源码包，仅为开发启动桩",
        "items": [],
    }


def export_order_hub_bom(db, purchase_no: str, **_kwargs) -> tuple[bytes, str]:
    raise ValueError("订单中枢 BOM 导出模块缺失（开发桩）")


def list_nudges(db, **_kwargs) -> list[dict]:
    return []


def role_matches_hint(role: str = "", hint: str = "") -> bool:
    if not hint:
        return True
    return (role or "").strip().lower() == (hint or "").strip().lower()
