"""SMB 会话（开发桩）。"""
from __future__ import annotations

from typing import Any


def is_smb_conn_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "connection" in text and ("limit" in text or "too many" in text)


def smb_close_host(*_args: Any, **_kwargs: Any) -> None:
    return None


def smb_register_with_retry(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("smb_session 未包含在本源码包（开发桩）")


def win_net_use(*_args: Any, **_kwargs: Any) -> None:
    return None


def win_net_use_delete(*_args: Any, **_kwargs: Any) -> None:
    return None
