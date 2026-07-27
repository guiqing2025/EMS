import hashlib
import hmac
import secrets
import time

from config import load_config

TOKEN_TTL_SECONDS = 24 * 3600
_TOKEN_SALT = "ems-dashboard-v1"


def get_dashboard_password() -> str:
    return load_config().get("dashboard_password", "")


def is_dashboard_locked() -> bool:
    return bool(get_dashboard_password())


def verify_password(password: str) -> bool:
    expected = get_dashboard_password()
    if not expected:
        return False
    return secrets.compare_digest(password, expected)


def _signing_key() -> bytes:
    pwd = get_dashboard_password()
    return hashlib.sha256(f"{_TOKEN_SALT}:{pwd}".encode()).digest()


def create_token() -> str:
    ts = int(time.time())
    payload = str(ts).encode()
    sig = hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def verify_token(token: str) -> bool:
    if not is_dashboard_locked():
        return True
    if not token or "." not in token:
        return False
    ts_str, sig = token.split(".", 1)
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if time.time() - ts > TOKEN_TTL_SECONDS:
        return False
    expected = hmac.new(_signing_key(), ts_str.encode(), hashlib.sha256).hexdigest()
    return secrets.compare_digest(sig, expected)
