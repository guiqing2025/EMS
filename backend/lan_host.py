"""局域网主机解析（开发桩）。"""
from __future__ import annotations

import socket


def resolve_machine_host(name: str = "", default: str = "127.0.0.1") -> str:
    host = (name or "").strip() or default
    try:
        socket.gethostbyname(host)
        return host
    except OSError:
        return default
