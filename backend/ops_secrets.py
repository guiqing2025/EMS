"""运维口令（开发桩）。"""
from __future__ import annotations

import os


def order_delete_password() -> str:
    return (os.environ.get("EMS_ORDER_DELETE_PASSWORD") or "dev-delete").strip()
