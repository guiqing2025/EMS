"""客诉（开发桩）。"""
from __future__ import annotations

from typing import Any


def dashboard_stats(*_args, **_kwargs) -> dict[str, Any]:
    return {"total": 0}


def filter_meta(*_args, **_kwargs) -> dict[str, Any]:
    return {"statuses": [], "customers": []}


def get_image_file(*_args, **_kwargs):
    raise FileNotFoundError("complaint_service 开发桩无图片")


def import_complaint_excel(*_args, **_kwargs) -> dict[str, Any]:
    raise ValueError("complaint_service 未包含在本源码包")


def list_batches(*_args, **_kwargs) -> list[dict]:
    return []


def list_details(*_args, **_kwargs) -> list[dict]:
    return []
