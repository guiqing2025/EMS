import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from config import load_config
from database import SessionLocal
from user_service import get_user_by_username, verify_password

TOKEN_TTL_SECONDS = 12 * 3600
_TOKEN_SALT = "ems-system-v2"

# 数据看板（出货对照）仅开放给这些账号
DASHBOARD_VIEWER_USERNAMES = frozenset({"dx001", "dx002", "dx003", "wgq"})


@dataclass
class AuthPrincipal:
    user_id: int
    username: str
    role: str
    department: Optional[str] = None
    display_name: str = ""

    @property
    def is_floor(self) -> bool:
        return self.role == "floor"

    @property
    def is_packing(self) -> bool:
        """仅包装入库扫码（无工序扫码）"""
        return self.role == "packing"

    @property
    def can_ship(self) -> bool:
        return self.role in ("admin", "planner", "warehouse")

    @property
    def is_warehouse(self) -> bool:
        return self.role in ("admin", "warehouse", "pmc", "eng_auditor")

    @property
    def is_planner(self) -> bool:
        return self.role in ("admin", "planner")

    @property
    def is_engineering(self) -> bool:
        return self.role == "engineering"

    @property
    def is_eng_auditor(self) -> bool:
        return self.role == "eng_auditor"

    @property
    def can_eng_import(self) -> bool:
        """导入 BOM / 坐标 / Gerber / 位号图"""
        return self.role in ("admin", "planner", "engineering")

    @property
    def can_eng_audit(self) -> bool:
        """审核机型资料、确认贴装主数据"""
        return self.role in ("admin", "planner", "eng_auditor")

    @property
    def can_eng_view(self) -> bool:
        return self.role in ("admin", "planner", "engineering", "eng_auditor")

    @property
    def is_dept(self) -> bool:
        return self.role == "dept"

    @property
    def is_hr(self) -> bool:
        return self.role in ("admin", "hr")

    # —— 流程图泳道角色（阶段 0 起）——
    @property
    def is_sales(self) -> bool:
        return self.role in ("admin", "sales", "pmc")

    @property
    def is_purchasing(self) -> bool:
        return self.role in ("admin", "purchasing", "pmc", "planner")

    @property
    def is_production(self) -> bool:
        return self.role in ("admin", "production", "planner", "pmc", "floor")

    @property
    def is_quality(self) -> bool:
        return self.role in ("admin", "quality", "pmc", "eng_auditor")

    @property
    def is_finance(self) -> bool:
        return self.role in ("admin", "finance")

    @property
    def can_view_dashboard(self) -> bool:
        return (self.username or "").strip().lower() in DASHBOARD_VIEWER_USERNAMES


def get_login_username() -> str:
    return (load_config().get("login_username") or "admin").strip()


def get_login_password() -> str:
    cfg = load_config()
    return (cfg.get("login_password") or cfg.get("dashboard_password") or "").strip()


def verify_config_admin(username: str, password: str) -> bool:
    expected_user = get_login_username()
    expected_pwd = get_login_password()
    if not expected_user or not expected_pwd:
        return False
    return secrets.compare_digest(username.strip(), expected_user) and secrets.compare_digest(
        password, expected_pwd
    )


def authenticate_user(db: Session, username: str, password: str) -> Tuple[Optional[AuthPrincipal], bool]:
    username = username.strip()
    row = get_user_by_username(db, username)
    if row and verify_password(password, row.password_hash):
        return AuthPrincipal(
            user_id=row.id,
            username=row.username,
            role=row.role,
            department=row.department,
            display_name=row.display_name or row.username,
        ), row.must_change_password
    # 同名员工账号已存在时，禁止用配置管理员密码回退成 admin（避免 WGQ 等被升权）
    from models import User

    if db.query(User).filter(User.username == username).first():
        return None, False
    if verify_config_admin(username, password):
        return AuthPrincipal(
            user_id=0,
            username=get_login_username(),
            role="admin",
            department=None,
            display_name=get_login_username(),
        ), False
    return None, False


def _signing_key() -> bytes:
    secret = f"{get_login_username()}:{get_login_password()}"
    return hashlib.sha256(f"{_TOKEN_SALT}:{secret}".encode()).digest()


def create_token(principal: AuthPrincipal) -> str:
    ts = int(time.time())
    dept = principal.department or ""
    payload = f"{ts}.{principal.user_id}.{principal.role}.{dept}"
    sig = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_legacy_token(token: str) -> Optional[AuthPrincipal]:
    if "." not in token:
        return None
    parts = token.split(".")
    if len(parts) != 2:
        return None
    ts_str, sig = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return None
    if time.time() - ts > TOKEN_TTL_SECONDS:
        return None
    expected = hmac.new(_signing_key(), ts_str.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(sig, expected):
        return None
    return AuthPrincipal(
        user_id=0,
        username=get_login_username(),
        role="admin",
        department=None,
        display_name=get_login_username(),
    )


def parse_token(token: str) -> Optional[AuthPrincipal]:
    if not token or "." not in token:
        return None
    parts = token.split(".")
    if len(parts) == 2:
        return _verify_legacy_token(token)
    if len(parts) != 5:
        return None
    ts_str, uid_str, role, dept, sig = parts
    try:
        ts = int(ts_str)
        user_id = int(uid_str)
    except ValueError:
        return None
    if time.time() - ts > TOKEN_TTL_SECONDS:
        return None
    payload = f"{ts_str}.{uid_str}.{role}.{dept}"
    expected = hmac.new(_signing_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(sig, expected):
        return None

    if user_id == 0:
        return AuthPrincipal(
            user_id=0,
            username=get_login_username(),
            role="admin",
            department=None,
            display_name="系统管理员",
        )

    db = SessionLocal()
    try:
        from models import User

        row = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if not row:
            return None
        return AuthPrincipal(
            user_id=row.id,
            username=row.username,
            role=row.role,
            department=row.department,
            display_name=row.display_name or row.username,
        )
    finally:
        db.close()


def verify_token(token: str) -> bool:
    return parse_token(token) is not None


def user_must_change_password(user_id: int) -> bool:
    if user_id == 0:
        return False
    db = SessionLocal()
    try:
        from models import User

        row = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        return bool(row and row.must_change_password)
    finally:
        db.close()


def require_system_auth(
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    access_token: Optional[str] = Query(None, alias="access_token"),
) -> AuthPrincipal:
    principal = parse_token(x_auth_token or access_token or "")
    if not principal:
        raise HTTPException(status_code=401, detail="请先登录系统")
    return principal


def require_admin(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    return principal


def require_hr(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if not principal.is_hr:
        raise HTTPException(status_code=403, detail="无人事管理权限")
    return principal


def require_admin_or_planner(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if principal.role not in ("admin", "planner"):
        raise HTTPException(status_code=403, detail="无操作权限")
    return principal


def require_dashboard_viewer(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if not principal.can_view_dashboard:
        raise HTTPException(status_code=403, detail="无数据看板权限")
    return principal


def require_eng_import(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if not principal.can_eng_import:
        raise HTTPException(status_code=403, detail="无工程资料导入权限")
    return principal


def is_global_admin_username(username: str = "") -> bool:
    name = (username or "").strip().lower()
    return name in {"admin", "wgq", "dx001"}


def is_ship_approver_username(username: str = "") -> bool:
    name = (username or "").strip().lower()
    return name in {"admin", "wgq", "dx001", "dx002"} or name.endswith("approve")


def is_ship_operator_username(username: str = "") -> bool:
    name = (username or "").strip().lower()
    return bool(name)


def require_manual_order(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if principal.role not in ("admin", "planner", "pmc", "warehouse"):
        raise HTTPException(status_code=403, detail="无手工建单权限")
    return principal


def require_order_delete(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if principal.role not in ("admin", "planner"):
        raise HTTPException(status_code=403, detail="无订单删除权限")
    return principal


def require_quality(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    if principal.role not in ("admin", "planner", "quality", "eng_auditor"):
        raise HTTPException(status_code=403, detail="无品质模块权限")
    return principal


