"""工程发料打印（开发桩）。"""
from __future__ import annotations

from typing import Any, Optional


def list_issue_print_logs(*_args, **_kwargs) -> list[dict]:
    return []


def record_issue_print_log(*_args, **_kwargs) -> dict[str, Any]:
    return {"ok": True, "stub": True}


def resolve_line_key_for_bom(*_args, **_kwargs) -> str:
    return ""
