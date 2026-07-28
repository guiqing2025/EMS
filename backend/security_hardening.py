"""API 安全：全站鉴权兜底、限流、脱敏响应。"""
from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse

from config import load_config
from system_auth import parse_token

# 无需登录即可访问（其余 /api/* 必须有效 Token；ict-gate 用 API Key）
PUBLIC_API_PREFIXES = (
    "/api/auth/login",
    "/api/auth/status",
)
PUBLIC_API_EXACT = frozenset(
    {
        "/api/health",
    }
)

# 探测常用路径直接 404（减少指纹）
PROBE_PATH_PREFIXES = (
    "/.env",
    "/.git",
    "/wp-admin",
    "/wp-login",
    "/phpmyadmin",
    "/admin.php",
    "/actuator",
    "/server-status",
    "/config.json",
    "/srm_config",
)


class RateLimiter:
    """简易内存滑动窗口限流（单机足够）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_sec: float) -> bool:
        now = time.time()
        with self._lock:
            q = self._hits[key]
            cutoff = now - window_sec
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


_limiter = RateLimiter()


def security_cfg() -> dict:
    import os

    cfg = load_config().get("security") or {}
    default_origins = [
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://localhost:8001",
        "http://localhost:5173",
    ]
    origins = list(cfg.get("cors_origins") or default_origins)
    extra = (os.environ.get("EMS_CORS_ORIGINS") or "").strip()
    if extra:
        for part in extra.split(","):
            o = part.strip().rstrip("/")
            if o and o not in origins:
                origins.append(o)
    # 内网任意主机 IP（不绑死某一台机器地址）
    origin_regex = cfg.get("cors_origin_regex") or (
        r"https?://("
        r"localhost|127\.0\.0\.1|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
        r")(:\d+)?$"
    )
    return {
        "rate_limit_enabled": bool(cfg.get("rate_limit_enabled", True)),
        "login_per_minute": int(cfg.get("login_per_minute") or 20),
        "api_per_minute": int(cfg.get("api_per_minute") or 600),
        "ict_gate_per_minute": int(cfg.get("ict_gate_per_minute") or 300),
        "cors_origins": origins,
        "cors_origin_regex": origin_regex,
    }


def client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _ict_gate_key_ok(request: Request) -> bool:
    expected = ((load_config().get("ict") or {}).get("gate_api_key") or "").strip()
    if not expected:
        return False
    provided = (request.headers.get("X-Api-Key") or request.query_params.get("api_key") or "").strip()
    if not provided:
        return False
    try:
        return secrets.compare_digest(provided, expected)
    except Exception:
        return False


def is_public_api(path: str) -> bool:
    if path in PUBLIC_API_EXACT:
        return True
    for p in PUBLIC_API_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return True
    return False


def is_probe_path(path: str) -> bool:
    low = path.lower()
    for p in PROBE_PATH_PREFIXES:
        if low == p or low.startswith(p + "/") or low.startswith(p):
            return True
    return False


def check_rate_limit(request: Request) -> Optional[JSONResponse]:
    cfg = security_cfg()
    if not cfg["rate_limit_enabled"]:
        return None
    path = request.url.path
    ip = client_ip(request)
    if path.startswith("/api/auth/login"):
        ok = _limiter.allow(f"login:{ip}", cfg["login_per_minute"], 60.0)
        if not ok:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    elif path.startswith("/api/ict-gate"):
        ok = _limiter.allow(f"ict:{ip}", cfg["ict_gate_per_minute"], 60.0)
        if not ok:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    elif path.startswith("/api/"):
        ok = _limiter.allow(f"api:{ip}", cfg["api_per_minute"], 60.0)
        if not ok:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    return None


def check_api_auth(request: Request) -> Optional[JSONResponse]:
    """全站 /api 鉴权兜底：未登录统一 401，不暴露路由细节。"""
    path = request.url.path
    if not path.startswith("/api/"):
        return None
    if is_public_api(path):
        return None
    if path.startswith("/api/ict-gate"):
        if _ict_gate_key_ok(request):
            return None
        return JSONResponse(status_code=401, content={"detail": "未授权"})
    token = request.headers.get("X-Auth-Token") or request.query_params.get("access_token")
    if token and parse_token(token):
        return None
    return JSONResponse(status_code=401, content={"detail": "请先登录系统"})


def security_headers(response) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # 不主动声明技术栈
    if "server" in response.headers:
        del response.headers["server"]
