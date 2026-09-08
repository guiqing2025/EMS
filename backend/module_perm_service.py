"""账号子页权限：勾选即开、去掉即关，立即写库生效。"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import User
from system_auth import is_global_admin_username

# 子页目录（与前端 menu key 对齐）
PAGE_CATALOG: list[dict[str, str]] = [
    {"key": "dashboard", "group": "首页", "title": "首页看板"},
    {"key": "quotation", "group": "报价", "title": "订单报价"},
    {"key": "orders-list", "group": "订单中心", "title": "订单列表"},
    {"key": "laser-register", "group": "订单中心", "title": "镭雕登记"},
    {"key": "production-daily", "group": "生产", "title": "生产日报"},
    {"key": "warehouse-materials", "group": "仓库管理", "title": "物料明细"},
    {"key": "warehouse-finished", "group": "仓库管理", "title": "成品库存"},
    {"key": "warehouse-pack-boxes", "group": "仓库管理", "title": "批次记录"},
    {"key": "warehouse-tooling", "group": "仓库管理", "title": "工装登记"},
    {"key": "eng-docs", "group": "工程管理", "title": "工程资料"},
    {"key": "eng-control", "group": "工程管理", "title": "物料管制"},
    {"key": "eng-sub", "group": "工程管理", "title": "替代料"},
    {"key": "eng-process", "group": "工程管理", "title": "工序对照"},
    {"key": "sch-master", "group": "计划排产", "title": "生产主计划"},
    {"key": "sch-smt", "group": "计划排产", "title": "SMT 排产"},
    {"key": "sch-dip", "group": "计划排产", "title": "DIP 排产"},
    {"key": "qc-aoi-repair", "group": "品质管理", "title": "AOI维修改判"},
    {"key": "qc-process-defects", "group": "品质管理", "title": "制程不良看板"},
    {"key": "qc-complaints", "group": "品质管理", "title": "客诉看板"},
    {"key": "qc-barcode-trace", "group": "品质管理", "title": "条码追溯"},
    {"key": "qc-dip-first-article", "group": "品质管理", "title": "DIP首件"},
    {"key": "qc-smt-ipqc", "group": "品质管理", "title": "SMT巡检"},
    {"key": "hr-staff", "group": "人事管理", "title": "员工档案"},
    {"key": "hr-attendance", "group": "人事管理", "title": "请假登记"},
    {"key": "settings-sync", "group": "系统设置", "title": "同步状态"},
    {"key": "settings-account-perms", "group": "系统设置", "title": "账号权限"},
    {"key": "pda", "group": "PDA", "title": "PDA 扫码"},
]

ALL_PAGE_KEYS = frozenset(p["key"] for p in PAGE_CATALOG)
# 全局管理员（WGQ / dx001）不可关掉账号权限与同步状态
GLOBAL_ADMIN_LOCKED_KEYS = frozenset({"settings-account-perms", "settings-sync"})
WGQ_LOCKED_KEYS = GLOBAL_ADMIN_LOCKED_KEYS  # 兼容旧名
ADMIN_LOCKED_KEYS = frozenset({"settings-sync"})

# 角色默认子页（与历史菜单大致对齐）
ROLE_DEFAULT_PAGES: dict[str, list[str]] = {
    # admin 默认不含「账号权限」（仅全局管理员可见）
    "admin": sorted(ALL_PAGE_KEYS - {"settings-account-perms"}),
    # PMC：与管理员相同，但不含数据看板、订单报价、账号权限
    "pmc": sorted(ALL_PAGE_KEYS - {"dashboard", "quotation", "settings-account-perms"}),
    "planner": [
        "orders-list",
        "laser-register",
        "production-daily",
        "warehouse-finished",
        "warehouse-pack-boxes",
        "warehouse-tooling",
        "eng-docs",
        "eng-control",
        "eng-sub",
        "eng-process",
        "sch-master",
        "sch-smt",
        "sch-dip",
        "qc-aoi-repair",
        "qc-process-defects",
        "qc-complaints",
        "qc-barcode-trace",
        "qc-dip-first-article",
        "qc-smt-ipqc",
        "pda",
    ],
    "warehouse": [
        "orders-list",
        "production-daily",
        "warehouse-materials",
        "warehouse-finished",
        "warehouse-pack-boxes",
        "warehouse-tooling",
        "eng-control",
        "pda",
    ],
    "engineering": ["orders-list", "eng-docs", "eng-control", "eng-sub"],
    "eng_importer": [
        "orders-list",
        "eng-docs",
        "eng-control",
        "eng-sub",
        "eng-process",
    ],
    "eng_viewer": ["orders-list", "eng-docs", "eng-control"],
    "eng_auditor": [
        "orders-list",
        "warehouse-materials",
        "warehouse-finished",
        "warehouse-pack-boxes",
        "warehouse-tooling",
        "eng-docs",
        "eng-control",
    ],
    "floor": ["orders-list", "pda"],
    "packing": ["orders-list", "pda", "warehouse-pack-boxes"],
    "smt_scan": ["orders-list", "pda"],
    "laser": ["laser-register", "pda"],
    "hr": ["hr-staff", "hr-attendance"],
}

# 用户名额外默认（历史白名单）
USERNAME_BONUS_PAGES: dict[str, list[str]] = {
    "dx001": ["dashboard", "quotation", "settings-account-perms"],
    "dx002": ["dashboard"],
    "dx003": ["dashboard"],
    "wgq": ["dashboard", "quotation", "settings-account-perms"],
    # 黄星：品质改判 + 工程全局（替代料/工序对照）+ 生产日报（含编码明细/复制）
    "dxsmt001": ["qc-aoi-repair", "eng-sub", "eng-process", "production-daily"],
    # 邱梦林 / 任玉娴：工程管理全套子页（资料/管制/替代料/工序）
    "dxgc": ["eng-docs", "eng-control", "eng-sub", "eng-process", "warehouse-pack-boxes", "warehouse-finished"],
    "dxgc002": ["eng-docs", "eng-control", "eng-sub", "eng-process", "warehouse-pack-boxes", "warehouse-finished"],
}


def _parse_stored(raw: Optional[str]) -> Optional[list[str]]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    if isinstance(data, dict) and isinstance(data.get("pages"), list):
        pages = data["pages"]
    elif isinstance(data, list):
        pages = data
    else:
        return None
    out = [str(x).strip() for x in pages if str(x).strip() in ALL_PAGE_KEYS]
    return sorted(set(out))


def role_default_pages(role: str, username: str = "") -> list[str]:
    role = (role or "").strip()
    pages = set(ROLE_DEFAULT_PAGES.get(role, ["orders-list", "pda"]))
    name = (username or "").strip().lower()
    for k in USERNAME_BONUS_PAGES.get(name, []):
        if k in ALL_PAGE_KEYS:
            pages.add(k)
    if role == "admin":
        pages |= ADMIN_LOCKED_KEYS
    if is_global_admin_username(name):
        pages |= GLOBAL_ADMIN_LOCKED_KEYS
        pages.add("settings-account-perms")
    return sorted(pages)


def effective_pages(user: User) -> tuple[list[str], str]:
    """返回 (pages, mode) mode=custom|role"""
    name = (user.username or "").strip().lower()
    stored = _parse_stored(getattr(user, "module_perms", None))
    if stored is not None:
        pages = set(stored)
        if (user.role or "") == "admin":
            pages |= ADMIN_LOCKED_KEYS
        if is_global_admin_username(name):
            pages |= GLOBAL_ADMIN_LOCKED_KEYS
            pages.add("settings-account-perms")
        elif "settings-account-perms" in pages:
            pages.discard("settings-account-perms")
        # 工程全局管理：custom 勾选也并上替代料/工序（避免漏配菜单）
        for k in USERNAME_BONUS_PAGES.get(name, []):
            if k in ALL_PAGE_KEYS:
                pages.add(k)
        return sorted(pages), "custom"
    return role_default_pages(user.role or "", user.username or ""), "role"


def serialize_perms(pages: list[str]) -> str:
    clean = sorted({p for p in pages if p in ALL_PAGE_KEYS})
    return json.dumps({"pages": clean}, ensure_ascii=False)


def set_page_enabled(db: Session, user: User, page_key: str, enabled: bool) -> dict[str, Any]:
    key = (page_key or "").strip()
    if key not in ALL_PAGE_KEYS:
        raise ValueError("未知子页")
    role = (user.role or "").strip()
    name = (user.username or "").strip().lower()
    if is_global_admin_username(name) and key in GLOBAL_ADMIN_LOCKED_KEYS and not enabled:
        raise ValueError("全局管理员不可关闭系统设置关键权限")
    if role == "admin" and key in ADMIN_LOCKED_KEYS and not enabled:
        raise ValueError("管理员不可关闭同步状态")
    if key == "settings-account-perms" and not is_global_admin_username(name) and enabled:
        raise ValueError("账号权限仅限 WGQ / dx001")
    pages, _ = effective_pages(user)
    s = set(pages)
    if enabled:
        s.add(key)
    else:
        s.discard(key)
    if role == "admin":
        s |= ADMIN_LOCKED_KEYS
    if is_global_admin_username(name):
        s |= GLOBAL_ADMIN_LOCKED_KEYS
    else:
        s.discard("settings-account-perms")
    user.module_perms = serialize_perms(sorted(s))
    db.add(user)
    db.commit()
    db.refresh(user)
    pages2, mode = effective_pages(user)
    return {
        "user_id": user.id,
        "username": user.username,
        "mode": mode,
        "pages": pages2,
        "page_key": key,
        "enabled": key in pages2,
    }


def list_account_perm_matrix(db: Session) -> dict[str, Any]:
    rows = db.query(User).order_by(User.role.asc(), User.username.asc()).all()
    users_out = []
    for u in rows:
        pages, mode = effective_pages(u)
        users_out.append(
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name or "",
                "role": u.role or "",
                "department": u.department or "",
                "is_active": bool(u.is_active),
                "mode": mode,
                "pages": pages,
            }
        )
    return {"catalog": PAGE_CATALOG, "users": users_out}
