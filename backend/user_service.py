"""系统用户（仓库/部门账号）"""
from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from models import User

PBKDF2_ITERATIONS = 120_000

EXECUTIVE_ACCOUNTS = [
    ("dx001", "廖总", "admin", None, "88888888"),
    ("dx002", "车总", "admin", None, "88888888"),
    ("dx003", "王总", "admin", None, "88888888"),  # 兼工程资料审核（与黄星并列）
]

STAFF_ACCOUNTS = [
    ("PMC", "陈小妹", "pmc", None, "888888"),
    ("dxck", "许敏", "warehouse", None, "888888"),  # 仓库组长
    ("dxgc", "邱梦林", "admin", None, "888888"),  # 全局权限（原工程资料导入）
    ("WGQ", "系统管理员", "admin", None, "jb140313!"),  # 全局管理 + 工程审核
    ("dxgc002", "任玉娴", "admin", None, "888888"),
    ("dxxz", "许瑞娇", "hr", None, "888888"),  # 仅人事管理
    ("dxsmt001", "黄星", "eng_auditor", None, "888888"),  # 工程资料审核
    # 产线扫码：订单列表 + 工序/包装扫码 + 查看管制（不可发货）
    ("dxd1cj", "产线扫码-插件", "floor", None, "888888"),
    ("dxd1hh", "产线扫码-后焊", "floor", None, "888888"),
    ("dxd2cj", "产线扫码-插件", "floor", None, "888888"),
    ("dxd2hh", "产线扫码-后焊", "floor", None, "888888"),
    ("dxsf", "产线扫码-三防", "floor", None, "888888"),
    # 包装扫码：仅订单列表 + 包装入库扫码（无工序扫码、无发货）
    ("dxbz001", "匡小落", "packing", None, "888888"),
]


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, expected = stored.split("$", 1)
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()
    return secrets.compare_digest(actual, expected)


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username.strip(), User.is_active.is_(True)).first()


def upsert_user(
    db: Session,
    username: str,
    display_name: str,
    role: str,
    department: Optional[str],
    password: str,
    *,
    must_change_password: bool = False,
    reset_password: bool = False,
) -> User:
    row = db.query(User).filter(User.username == username).first()
    if row:
        row.display_name = display_name
        row.role = role
        row.department = department
        row.is_active = True
        if reset_password:
            row.password_hash = hash_password(password)
            row.must_change_password = must_change_password
        return row
    row = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
        department=department,
        is_active=True,
        must_change_password=must_change_password,
    )
    db.add(row)
    return row


def ensure_default_users(db: Session) -> None:
    defaults = [
        ("warehouse", "仓库管理员", "warehouse", None, "888888"),
        ("planner", "计划员", "planner", None, "888888"),
        ("smt", "SMT", "dept", "smt", "888888"),
        ("dip", "DIP", "dept", "dip", "888888"),
    ]
    for username, display_name, role, department, password in defaults:
        row = db.query(User).filter(User.username == username).first()
        if row:
            continue
        db.add(
            User(
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
                role=role,
                department=department,
                is_active=True,
                must_change_password=False,
            )
        )

    # 旧账号 engineering → dxgc002（保留密码哈希，升为管理员）
    legacy = db.query(User).filter(User.username == "engineering").first()
    target = db.query(User).filter(User.username == "dxgc002").first()
    if legacy and not target:
        legacy.username = "dxgc002"
        legacy.display_name = legacy.display_name or "任玉娴"
        legacy.role = "admin"
        legacy.department = None
        legacy.is_active = True
        db.flush()
    elif legacy and target:
        # 新账号已存在时，停用旧账号，避免同人双账号
        legacy.is_active = False
        target.role = "admin"
        target.is_active = True
        db.flush()

    for username, display_name, role, department, password in EXECUTIVE_ACCOUNTS:
        row = db.query(User).filter(User.username == username).first()
        if row:
            if row.display_name != display_name:
                row.display_name = display_name
            row.role = role
            row.department = department
            row.is_active = True
            continue
        db.add(
            User(
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
                role=role,
                department=department,
                is_active=True,
                must_change_password=True,
            )
        )

    for username, display_name, role, department, password in STAFF_ACCOUNTS:
        row = db.query(User).filter(User.username == username).first()
        if row:
            row.display_name = display_name
            row.role = role
            row.is_active = True
            # 产线/包装扫码账号：确保角色/密码与种子一致（便于统一重置）
            if role in ("floor", "packing"):
                row.password_hash = hash_password(password)
                row.must_change_password = False
            continue
        db.add(
            User(
                username=username,
                display_name=display_name,
                password_hash=hash_password(password),
                role=role,
                department=department,
                is_active=True,
                must_change_password=False,
            )
        )

    db.commit()
