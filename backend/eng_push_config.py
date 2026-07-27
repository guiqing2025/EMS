"""工程资料账号推送配置（系统内待办）。

资料员 邱梦林（dxgc）← 退回 / 待导入
审核员 黄星（dxsmt001）、王总（dx003）← 待审核
"""
from __future__ import annotations

# 资料员：导入、收退回推送
ENG_IMPORTER_USERNAMES = frozenset({"dxgc"})
# 审核员：收待审推送（另含角色 eng_auditor）
ENG_AUDITOR_USERNAMES = frozenset({"dxsmt001", "dx003", "wgq"})

# 展示名（日志/文案）
ENG_PUSH_DISPLAY_NAMES = {
    "dxgc": "邱梦林",
    "dxsmt001": "黄星",
    "dx003": "王总",
    "wgq": "系统管理员",
}


def normalize_username(username: str | None) -> str:
    return (username or "").strip().lower()


def is_eng_importer_user(username: str | None = None, role: str | None = None) -> bool:
    user = normalize_username(username)
    role = (role or "").strip()
    if user in ENG_IMPORTER_USERNAMES:
        return True
    return role == "engineering"


def is_eng_auditor_user(username: str | None = None, role: str | None = None) -> bool:
    user = normalize_username(username)
    role = (role or "").strip()
    if user in ENG_AUDITOR_USERNAMES:
        return True
    # 其它管理员可看待审；资料员 dxgc 除外
    if role == "admin" and user not in ENG_IMPORTER_USERNAMES:
        return True
    return role == "eng_auditor"


def primary_importer_username() -> str:
    return "dxgc"


def display_name_for(username: str | None) -> str:
    user = normalize_username(username)
    return ENG_PUSH_DISPLAY_NAMES.get(user) or (username or "")
