"""条码追溯（开发桩）。"""
from __future__ import annotations

from typing import Any


def batch_trace_barcodes(*_args, **_kwargs) -> list[dict]:
    return []


def batch_trace_summary(*_args, **_kwargs) -> dict[str, Any]:
    return {"total": 0, "items": []}


def lookup_barcode_trace(*_args, **_kwargs) -> dict[str, Any]:
    return {"found": False, "message": "barcode_trace_service 开发桩"}


def search_batch_trace_options(*_args, **_kwargs) -> list[dict]:
    return []
