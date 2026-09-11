"""工序不良（开发桩）。"""
from __future__ import annotations

from typing import Any


def dashboard_stats(*_args, **_kwargs) -> dict[str, Any]:
    return {"total": 0}


def filter_meta(*_args, **_kwargs) -> dict[str, Any]:
    return {"processes": [], "defects": []}


def import_defect_excel(*_args, **_kwargs) -> dict[str, Any]:
    raise ValueError("process_defect_service 未包含在本源码包")


def list_defect_details(*_args, **_kwargs) -> list[dict]:
    return []


def list_import_batches(*_args, **_kwargs) -> list[dict]:
    return []
