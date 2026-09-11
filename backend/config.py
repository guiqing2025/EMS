import json
import os
from copy import deepcopy
from pathlib import Path
from typing import List, Optional

CONFIG_PATH = Path(__file__).parent / "srm_config.json"
# 仓库根目录下的本机路径覆盖（由 scripts/sync 从 env/*.example 生成，勿提交）
LOCAL_ENV_PATH = Path(__file__).resolve().parent.parent / "env" / "local.env"


def _load_local_env_file() -> None:
    """把 env/local.env 注入 os.environ（已存在的环境变量不覆盖）。"""
    if not LOCAL_ENV_PATH.is_file():
        return
    try:
        for raw in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


_load_local_env_file()


def _env_str(key: str) -> str:
    return (os.environ.get(key) or "").strip()


def share_root() -> Path:
    """共享盘根目录：EMS_SHARE_ROOT > 本机 Desktop/共享-测试软件资料。"""
    raw = _env_str("EMS_SHARE_ROOT")
    if raw:
        return Path(raw)
    return Path.home() / "Desktop" / "共享-测试软件资料"


def _path_from_env_or_config(env_key: str, config_key: str, *fallback_parts: str) -> str:
    """优先级：环境变量 > srm_config > 共享盘相对路径回退。"""
    from_env = _env_str(env_key)
    if from_env:
        return from_env
    cfg_val = ""
    try:
        cfg_val = (load_config_raw().get(config_key) or "").strip()
    except Exception:
        cfg_val = ""
    if cfg_val:
        return cfg_val
    if fallback_parts:
        return str(share_root().joinpath(*fallback_parts))
    return ""


_config_cache: Optional[dict] = None


def load_config_raw() -> dict:
    """仅读文件合并默认值，供路径解析避免递归。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        saved = _migrate_legacy_config(saved)
        cfg = {**DEFAULT_CONFIG, **saved}
    else:
        cfg = deepcopy(DEFAULT_CONFIG)
    _config_cache = cfg
    return cfg


def invalidate_config_cache() -> None:
    global _config_cache
    _config_cache = None

# 开发/出厂默认不预置任何真实客户；由本机 srm_config.json 配置
DEFAULT_CUSTOMERS: list = []

DEFAULT_CONFIG = {
    "sync_interval_minutes": 15,
    "sync_daily_hour": 9,
    "sync_daily_minute": 0,
    "auto_sync_enabled": False,
    "login_username": "sysadmin",
    "login_password": "jb140313!",
    "dashboard_password": "140313",
    "receive_board": {
        "history_start": "2026-01-01",
    },
    # 本机路径优先用环境变量 / env/local.env；此处仅作空缺时的相对回退根
    "warehouse_share_path": "",
    "warehouse_auto_sync_enabled": False,
    "warehouse_sync_interval_minutes": 120,
    # 工装登记：共享盘钢网/治具明细（相对 D-仓库表格）
    "tooling_stencil_path": "",
    "tooling_fixture_path": "",
    "tooling_auto_sync_enabled": False,
    "tooling_sync_interval_minutes": 120,
    "substitution_file_path": "",
    "process_detail_file_path": "",
    # 工程 BOM/坐标/Gerber 已改为人工导入，不再扫描此目录；路径仍可供贴码登记表等模块定位上级「共享-测试软件资料」
    "engineering_share_base": "",
    "hr_roster_path": "",
    "laser_import_default_path": "",
    "laser_print_register_path": "",
    # 工程资料：齐套且文件审核无失败时自动通过（客户 rules.workflow.auto_approve 可单独关闭）
    "eng_auto_review_enabled": True,
    "engineering_customers": [],
    "customers": DEFAULT_CUSTOMERS,
}


def _normalize_customers(customers: list) -> list:
    normalized = []
    for item in customers:
        if not item.get("id"):
            continue
        normalized.append(
            {
                "id": item["id"],
                "name": item.get("name") or item["id"],
                "api_type": item.get("api_type") or "v1",
                "srm_base_url": (item.get("srm_base_url") or "").rstrip("/"),
                "api_path": item.get("api_path") or "",
                "login_name": (item.get("login_name") or "").strip(),
                "password": item.get("password") or "",
                "enabled": bool(item.get("enabled", True)),
                "order_remark": (item.get("order_remark") or "").strip(),
                "acct_id": (item.get("acct_id") or "").strip(),
                "entry_role": (item.get("entry_role") or "SRM").strip(),
            }
        )
    return normalized


def _migrate_legacy_config(saved: dict) -> dict:
    # 无预置客户：缺 customers 时写空列表，不注入历史客户模板
    if "customers" not in saved or saved.get("customers") is None:
        saved["customers"] = []
    return saved


def load_config() -> dict:
    invalidate_config_cache()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        saved = _migrate_legacy_config(saved)
        cfg = {**DEFAULT_CONFIG, **saved}
    else:
        cfg = deepcopy(DEFAULT_CONFIG)
    cfg["customers"] = _normalize_customers(cfg.get("customers") or DEFAULT_CUSTOMERS)
    if not (cfg.get("login_username") or "").strip():
        cfg["login_username"] = DEFAULT_CONFIG["login_username"]
    if not (cfg.get("login_password") or "").strip():
        cfg["login_password"] = DEFAULT_CONFIG["login_password"]
    if not (cfg.get("dashboard_password") or "").strip():
        cfg["dashboard_password"] = DEFAULT_CONFIG["dashboard_password"]
    # 路径字段：env 优先覆盖，便于 Mac/Windows 本机差异
    cfg["warehouse_share_path"] = get_warehouse_share_path()
    cfg["substitution_file_path"] = get_substitution_file_path()
    cfg["process_detail_file_path"] = get_process_detail_file_path()
    cfg["engineering_share_base"] = get_engineering_share_base()
    cfg["hr_roster_path"] = get_hr_roster_path()
    cfg["tooling_stencil_path"] = get_tooling_stencil_path()
    cfg["tooling_fixture_path"] = get_tooling_fixture_path()
    return cfg


def get_enabled_customers() -> List[dict]:
    return [c for c in load_config().get("customers", []) if c.get("enabled")]


def get_customer(customer_id: str) -> Optional[dict]:
    for customer in load_config().get("customers", []):
        if customer["id"] == customer_id:
            return customer
    return None


def get_warehouse_share_path() -> str:
    return _path_from_env_or_config(
        "WAREHOUSE_SHARE_PATH",
        "warehouse_share_path",
        "D-仓库表格",
        "客户进销表",
    )


def get_substitution_file_path() -> str:
    # 替代料常放在仓库旁；也可用 SUBSTITUTION_FILE_PATH 指向任意文件
    from_env = _env_str("SUBSTITUTION_FILE_PATH")
    if from_env:
        return from_env
    cfg_val = (load_config_raw().get("substitution_file_path") or "").strip()
    if cfg_val:
        return cfg_val
    return str(Path.home() / "Desktop" / "EMS" / "替代料06-03.xls")


def get_process_detail_file_path() -> str:
    from_env = _env_str("PROCESS_DETAIL_FILE_PATH")
    if from_env:
        return from_env
    cfg_val = (load_config_raw().get("process_detail_file_path") or "").strip()
    if cfg_val:
        return cfg_val
    return str(Path.home() / "Desktop" / "EMS" / "工艺明细.xlsx")


def get_engineering_share_base() -> str:
    return _path_from_env_or_config(
        "ENGINEERING_SHARE_BASE",
        "engineering_share_base",
        "A-生产 工程 品质共用文件夹",
    )


def get_hr_roster_path() -> str:
    return _path_from_env_or_config(
        "HR_ROSTER_PATH",
        "hr_roster_path",
        "B-行政 人事资料",
        "员工花名册.xlsx",
    )


def get_tooling_warehouse_dir() -> str:
    """D-仓库表格目录（钢网/治具明细所在）。"""
    from_env = _env_str("TOOLING_WAREHOUSE_DIR")
    if from_env:
        return from_env
    wh = get_warehouse_share_path()
    if wh:
        parent = str(Path(wh).parent)
        if parent and parent not in (".", ""):
            return parent
    return str(share_root() / "D-仓库表格")


def get_tooling_stencil_path() -> str:
    return _path_from_env_or_config(
        "TOOLING_STENCIL_PATH",
        "tooling_stencil_path",
        "D-仓库表格",
        "2026钢网明细单1月.xlsx",
    )


def get_tooling_fixture_path() -> str:
    return _path_from_env_or_config(
        "TOOLING_FIXTURE_PATH",
        "tooling_fixture_path",
        "D-仓库表格",
        "A-所有客户治具明细表（1）.xlsx",
    )


def get_laser_import_default_path() -> str:
    return _path_from_env_or_config(
        "LASER_IMPORT_DEFAULT_PATH",
        "laser_import_default_path",
    ) or str(Path.home() / "Desktop" / "镭雕记录表 - 副本.xlsx")


def get_laser_print_register_path() -> str:
    from_env = _env_str("LASER_PRINT_REGISTER_PATH")
    if from_env:
        return from_env
    cfg_val = (load_config_raw().get("laser_print_register_path") or "").strip()
    if cfg_val:
        return cfg_val
    return str(share_root() / "I-表格类" / "打印条码登记表.xlsx")


def get_engineering_customers() -> List[dict]:
    from eng_customer_rules import normalize_engineering_customer

    items = load_config().get("engineering_customers")
    if not isinstance(items, list) or not items:
        items = deepcopy(DEFAULT_CONFIG["engineering_customers"])
    return [normalize_engineering_customer(item) for item in items if isinstance(item, dict)]


def get_engineering_customer_by_code(internal_code: str) -> Optional[dict]:
    code = (internal_code or "").strip().upper()
    for item in get_engineering_customers():
        if (item.get("internal_code") or "").strip().upper() == code:
            return item
    return None


def get_engineering_customer_by_srm_id(customer_id: str) -> Optional[dict]:
    cid = (customer_id or "").strip()
    for item in get_engineering_customers():
        if (item.get("customer_id") or "").strip() == cid:
            return item
        aliases = item.get("customer_id_aliases") or []
        if any(str(a).strip() == cid for a in aliases):
            return item
    return None


def save_config(data: dict) -> dict:
    current = load_config_raw()
    current = {**DEFAULT_CONFIG, **current}
    current["customers"] = _normalize_customers(current.get("customers") or DEFAULT_CUSTOMERS)
    for key in (
        "sync_interval_minutes",
        "sync_daily_hour",
        "sync_daily_minute",
        "auto_sync_enabled",
        "login_username",
        "login_password",
        "dashboard_password",
        "warehouse_share_path",
        "warehouse_auto_sync_enabled",
        "warehouse_sync_interval_minutes",
        "tooling_stencil_path",
        "tooling_fixture_path",
        "tooling_auto_sync_enabled",
        "tooling_sync_interval_minutes",
        "substitution_file_path",
        "process_detail_file_path",
        "engineering_share_base",
        "hr_roster_path",
        "laser_import_default_path",
        "laser_print_register_path",
        "eng_auto_review_enabled",
        "engineering_customers",
    ):
        if key not in data:
            continue
        if key == "login_password":
            pwd = (data[key] or "").strip()
            if not pwd or pwd == "******":
                continue
            current["login_password"] = pwd
            continue
        if key == "dashboard_password":
            pwd = (data[key] or "").strip()
            if not pwd or pwd == "******":
                continue
            current["dashboard_password"] = pwd
            continue
        if key == "login_username":
            username = (data[key] or "").strip()
            if username:
                current["login_username"] = username
            continue
        current[key] = data[key]
    if "customers" in data and isinstance(data["customers"], list):
        incoming = {c["id"]: c for c in _normalize_customers(data["customers"])}
        merged = []
        for old in current["customers"]:
            item = {**old, **incoming.get(old["id"], {})}
            if incoming.get(old["id"], {}).get("password") in (None, "", "******"):
                item["password"] = old["password"]
            elif incoming.get(old["id"], {}).get("password") == "******":
                item["password"] = old["password"]
            merged.append(item)
        for cid, item in incoming.items():
            if not any(c["id"] == cid for c in merged):
                merged.append(item)
        current["customers"] = _normalize_customers(merged)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    invalidate_config_cache()
    return load_config()


def expand_customer_ids_for_filter(customer_id: str = "") -> list[str]:
    """把客户 ID 展开为自身 + 别名，供订单/工程筛选。"""
    cid = (customer_id or "").strip()
    if not cid:
        return []
    out = [cid]
    cust = get_customer(cid)
    if cust:
        for alias in cust.get("customer_id_aliases") or []:
            a = str(alias).strip()
            if a and a not in out:
                out.append(a)
    # 反向：若传入的是别名，找回主 ID
    for item in get_enabled_customers() or []:
        aliases = [str(a).strip() for a in (item.get("customer_id_aliases") or [])]
        if cid in aliases or cid == str(item.get("id") or "").strip():
            main = str(item.get("id") or "").strip()
            if main and main not in out:
                out.insert(0, main)
            for a in aliases:
                if a and a not in out:
                    out.append(a)
    return out

