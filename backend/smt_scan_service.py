"""SMT 扫码（开发桩）。"""
from __future__ import annotations

from typing import Any, Optional


def _guess_model_from_barcode(barcode: str = "") -> str:
    return ""


def scan_smt_manual(*_args, **_kwargs) -> dict[str, Any]:
    raise ValueError("smt_scan_service 未包含在本源码包")
