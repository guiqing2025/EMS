"""品质服务（开发桩）。"""
from __future__ import annotations

from typing import Any, Optional


def list_aoi_fails(*_args, **_kwargs) -> list[dict]:
    return []


def list_overrides(*_args, **_kwargs) -> list[dict]:
    return []


def lookup_aoi(*_args, **_kwargs) -> dict[str, Any]:
    return {"found": False, "message": "quality_service 开发桩"}


def override_aoi_to_pass(*_args, **_kwargs) -> dict[str, Any]:
    raise ValueError("quality_service 未包含在本源码包")


def resolve_qc_confirm_operator(*_args, **_kwargs) -> str:
    return "dev"
