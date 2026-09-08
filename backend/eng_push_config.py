"""工程资料账号推送配置（系统内待办）。

资料员 邱梦林（dxgc）、任玉娴（dxgc002）← 退回 / 待导入；并具备工程管理全局权限
审核员 黄星（dxsmt001）、王总（dx003）← 待审核
查看导出 王玉兰（dxpz001）← 不收待审/待导入推送
"""
from __future__ import annotations

# 资料员：导入、收退回推送
ENG_IMPORTER_USERNAMES = frozenset({"dxgc", "dxgc002"})
# 审核员：收待审推送（另含角色 eng_auditor，但不含仅查看账号）
ENG_AUDITOR_USERNAMES = frozenset({"dxsmt001", "dx003", "wgq"})
# 工程资料全局管理（导入+审核+导出+替代料/工序）：黄星 + 资料员邱梦林/任玉娴
ENG_FULL_MANAGER_USERNAMES = frozenset({"dxsmt001", "dxgc", "dxgc002"})
# 仅查看+导出：不进审核待办推送
ENG_VIEW_ONLY_USERNAMES = frozenset({"dxpz001"})

# 展示名（日志/文案）
ENG_PUSH_DISPLAY_NAMES = {
    "dxgc": "邱梦林",
    "dxgc002": "任玉娴",
    "dxsmt001": "黄星",
    "dx003": "王总",
    "wgq": "系统管理员",
    "dxpz001": "王玉兰",
}


def normalize_username(username: str | None) -> str:
    return (username or "").strip().lower()


def is_eng_view_only_user(username: str | None = None) -> bool:
    return normalize_username(username) in ENG_VIEW_ONLY_USERNAMES


def is_eng_full_manager_user(username: str | None = None) -> bool:
    return normalize_username(username) in ENG_FULL_MANAGER_USERNAMES


def is_eng_importer_user(username: str | None = None, role: str | None = None) -> bool:
    user = normalize_username(username)
    role = (role or "").strip()
    if user in ENG_VIEW_ONLY_USERNAMES or role == "eng_viewer":
        return False
    if is_eng_full_manager_user(user):
        return True
    if role in ("engineering", "eng_importer"):
        return True
    return user in ENG_IMPORTER_USERNAMES


def is_eng_auditor_user(username: str | None = None, role: str | None = None) -> bool:
    user = normalize_username(username)
    role = (role or "").strip()
    if user in ENG_VIEW_ONLY_USERNAMES or role == "eng_viewer":
        return False
    if is_eng_full_manager_user(user):
        return True
    if role == "eng_auditor":
        return True
    if user in ENG_AUDITOR_USERNAMES:
        return True
    # 其它管理员可看待审；资料员除外
    if role == "admin" and user not in ENG_IMPORTER_USERNAMES:
        return True
    return False


def primary_importer_username() -> str:
    return "dxgc"


def importer_usernames() -> tuple[str, ...]:
    return tuple(sorted(ENG_IMPORTER_USERNAMES))


def display_name_for(username: str | None) -> str:
    user = normalize_username(username)
    return ENG_PUSH_DISPLAY_NAMES.get(user) or (username or "")
