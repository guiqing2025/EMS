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

DEFAULT_CUSTOMERS = [
    {
        "id": "feilisi",
        "name": "菲利斯",
        "api_type": "v1",
        "srm_base_url": "http://139.159.240.251:19190",
        "api_path": "",
        "login_name": "FL00676",
        "password": "DX123456",
        "enabled": True,
    },
    {
        "id": "enjiu",
        "name": "恩玖·鼎雄",
        "api_type": "v2",
        "srm_base_url": "http://218.17.126.115:60801",
        "api_path": "/adpweb",
        "login_name": "100246",
        "password": "123456789",
        "enabled": True,
    },
    {
        "id": "yonglian",
        "name": "永联",
        "api_type": "kingdee",
        "srm_base_url": "http://k3.szwinline.com:8880",
        "api_path": "/k3cloud",
        "acct_id": "5d6dce3c732bc4",
        "entry_role": "SRM",
        "login_name": "07.01.0089",
        "password": "dx123456**",
        "enabled": True,
    },
    {
        "id": "yilanke",
        "name": "亿兰科",
        "api_type": "manual",
        "srm_base_url": "",
        "api_path": "",
        "login_name": "",
        "password": "",
        "enabled": True,
    },
]

DEFAULT_CONFIG = {
    "sync_interval_minutes": 15,
    "sync_daily_hour": 9,
    "sync_daily_minute": 0,
    "auto_sync_enabled": True,
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
    "substitution_file_path": "",
    "process_detail_file_path": "",
    # 工程 BOM/坐标/Gerber 已改为人工导入，不再扫描此目录；路径仍可供贴码登记表等模块定位上级「共享-测试软件资料」
    "engineering_share_base": "",
    "hr_roster_path": "",
    "laser_import_default_path": "",
    "laser_print_register_path": "",
    "engineering_customers": [
        {
            "internal_code": "A123",
            "customer_id": "feilisi",
            "name": "菲利斯",
            "bom_folder": "A123客户最新资料",
            "asset_folders": ["A123"],
            "rules": {
                "model_key_regex": r"1\d{2}-\d{6}-\d{2}",
                "bom_parse_profile": "feilisi",
                "assets_scope": "order",
                "checklist": {
                    "bom": True,
                    "placement": True,
                    "gerber": False,
                    "refmap": False,
                    "mount_resolved": True,
                },
            },
        },
        {
            "internal_code": "A116",
            "customer_id": "enjiu",
            "name": "恩玖·鼎雄",
            "bom_folder": "A116-NJ",
            "rules": {
                "model_key_regex": r"^(0\d{7,8}|99\d{6,8})",
                "bom_parse_profile": "enjiu",
                "assets_scope": "order",
                "model_code_variants": [
                    {"from_prefix": "03019", "to_prefix": "03029"},
                    {"from_prefix": "03029", "to_prefix": "03019"},
                ],
                "checklist": {
                    "bom": True,
                    "placement": True,
                    "gerber": False,
                    "refmap": False,
                    "mount_resolved": True,
                },
            },
        },
        {
            "internal_code": "A067",
            "customer_id": "yonglian",
            "name": "永联",
            "bom_folder": "A067-YL",
            "asset_folders": ["A067-YL"],
            "rules": {
                "model_key_regex": r"^(91\.\d{4}\.\d+|03\.\d{2}\.\d+|69\.\d{2}\.\d+)",
                "bom_parse_profile": "yonglian",
                "checklist": {
                    "bom": True,
                    "placement": True,
                    "gerber": False,
                    "refmap": False,
                    "mount_resolved": True,
                },
            },
        },
        {
            "internal_code": "A120",
            "customer_id": "yilanke",
            "customer_id_aliases": ["manual_daeae675", "wh_yilanke"],
            "name": "亿兰科",
            "bom_folder": "A120客户最新资料",
            "asset_folders": ["A120"],
            "rules": {
                "model_key_regex": r"^(3001-\d+[A-Za-z]?)",
                "bom_parse_profile": "yilanke",
                "checklist": {
                    "bom": True,
                    "placement": True,
                    "gerber": False,
                    "refmap": False,
                    "mount_resolved": True,
                },
            },
        },
    ],
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
    if saved.get("customers"):
        return saved
    legacy = {
        "id": "feilisi",
        "name": "菲利斯",
        "api_type": "v1",
        "srm_base_url": saved.get("srm_base_url", DEFAULT_CUSTOMERS[0]["srm_base_url"]),
        "api_path": "",
        "login_name": saved.get("login_name", DEFAULT_CUSTOMERS[0]["login_name"]),
        "password": saved.get("password", DEFAULT_CUSTOMERS[0]["password"]),
        "enabled": True,
    }
    customers = [legacy]
    for item in DEFAULT_CUSTOMERS:
        if item["id"] != "feilisi":
            customers.append(deepcopy(item))
    saved["customers"] = customers
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
        "鼎雄员工花名册.xlsx",
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
        "substitution_file_path",
        "process_detail_file_path",
        "engineering_share_base",
        "hr_roster_path",
        "laser_import_default_path",
        "laser_print_register_path",
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
