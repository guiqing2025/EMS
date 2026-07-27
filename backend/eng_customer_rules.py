"""工程客户规则：从 engineering_customers.rules 解析，带默认值。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

# 全局默认（未配置客户时的兜底）
DEFAULT_RULES: dict[str, Any] = {
    "model_key_regex": "",
    "model_code_variants": [],  # [{"from": "03019", "to": "03029"}] 或字符串对
    "bom_parse_profile": "auto",  # auto | feilisi | enjiu
    # model：同机型共用坐标/Gerber；order：按采购订单隔离（菲利斯）
    "assets_scope": "model",
    "checklist": {
        "bom": True,
        "placement": True,
        "gerber": False,
        "refmap": False,
        "mount_resolved": True,
    },
    "skip_folder_prefixes": ["000", "生产资料压缩包", "管制明细", "旧资料"],
    "mount": {
        "extra_smt_name_patterns": [],
        "extra_dip_name_patterns": [],
        "extra_assy_name_patterns": [],
    },
    "workflow": {
        "require_placement": True,
        "allow_approve_without_mount": False,
    },
}

# 按客户代号的内置默认（配置未写 rules 时补齐）
BUILTIN_CUSTOMER_RULES: dict[str, dict[str, Any]] = {
    "A123": {
        "model_key_regex": r"1\d{2}-\d{6}-\d{2}",
        "model_code_variants": [],
        "bom_parse_profile": "feilisi",
        "assets_scope": "order",
        "checklist": {
            "bom": True,
            "placement": True,
            "gerber": False,
            "refmap": False,
            "mount_resolved": True,
        },
        "mount": {
            "extra_smt_name_patterns": [],
            "extra_dip_name_patterns": [],
            "extra_assy_name_patterns": [],
        },
        "workflow": {
            "require_placement": True,
            "allow_approve_without_mount": False,
        },
    },
    "A116": {
        "model_key_regex": r"^(0\d{7,8}|99\d{6,8})",
        "model_code_variants": [
            {"from_prefix": "03019", "to_prefix": "03029"},
            {"from_prefix": "03029", "to_prefix": "03019"},
        ],
        "bom_parse_profile": "enjiu",
        # 同料号不同采购订单：坐标/Gerber 不共用，须各自导入
        "assets_scope": "order",
        "checklist": {
            "bom": True,
            "placement": True,
            "gerber": False,
            "refmap": False,
            "mount_resolved": True,
        },
        "mount": {
            "extra_smt_name_patterns": [],
            "extra_dip_name_patterns": [],
            "extra_assy_name_patterns": [],
        },
        "workflow": {
            "require_placement": True,
            "allow_approve_without_mount": False,
        },
    },
    "A067": {
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
    "A120": {
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
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = deepcopy(base)
    for key, val in (overlay or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


def normalize_customer_rules(internal_code: str, rules: Optional[dict] = None) -> dict[str, Any]:
    code = (internal_code or "").strip().upper()
    merged = deepcopy(DEFAULT_RULES)
    builtin = BUILTIN_CUSTOMER_RULES.get(code)
    if builtin:
        merged = _deep_merge(merged, builtin)
    if rules and isinstance(rules, dict):
        merged = _deep_merge(merged, rules)
    return merged


def normalize_engineering_customer(item: dict) -> dict:
    """补齐 rules，返回可序列化的客户配置副本。"""
    if not isinstance(item, dict):
        return {}
    out = deepcopy(item)
    code = (out.get("internal_code") or "").strip().upper()
    out["internal_code"] = code
    out["rules"] = normalize_customer_rules(code, out.get("rules") if isinstance(out.get("rules"), dict) else None)
    return out


def get_customer_rules(internal_code: str) -> dict[str, Any]:
    from config import get_engineering_customer_by_code

    cust = get_engineering_customer_by_code(internal_code)
    if cust:
        return normalize_customer_rules(
            cust.get("internal_code") or internal_code,
            cust.get("rules") if isinstance(cust.get("rules"), dict) else None,
        )
    return normalize_customer_rules(internal_code, None)


def resolve_model_code_variants(code: str, rules: dict) -> list[str]:
    """根据 rules.model_code_variants 生成料号变体列表（含自身）。"""
    text = (code or "").strip()
    if not text:
        return []
    variants = [text]
    for rule in rules.get("model_code_variants") or []:
        if isinstance(rule, str):
            continue
        if not isinstance(rule, dict):
            continue
        fp = (rule.get("from_prefix") or "").strip()
        tp = (rule.get("to_prefix") or "").strip()
        if not fp or not tp:
            continue
        if text.startswith(fp) and len(text) > len(fp):
            variants.append(tp + text[len(fp) :])
    return list(dict.fromkeys(variants))


def bom_parse_profile_for(internal_code: str) -> str:
    profile = (get_customer_rules(internal_code).get("bom_parse_profile") or "auto").strip().lower()
    if profile in ("feilisi", "a123"):
        return "feilisi"
    if profile in ("enjiu", "a116"):
        return "enjiu"
    if profile in ("yonglian", "a067"):
        return "yonglian"
    if profile in ("yilanke", "a120"):
        return "yilanke"
    return "auto"


def checklist_for(internal_code: str) -> dict[str, bool]:
    raw = get_customer_rules(internal_code).get("checklist") or {}
    return {
        "bom": bool(raw.get("bom", True)),
        "placement": bool(raw.get("placement", True)),
        "gerber": bool(raw.get("gerber", False)),
        "refmap": bool(raw.get("refmap", False)),
        "mount_resolved": bool(raw.get("mount_resolved", True)),
    }


def workflow_for(internal_code: str) -> dict[str, bool]:
    raw = get_customer_rules(internal_code).get("workflow") or {}
    return {
        "require_placement": bool(raw.get("require_placement", True)),
        "allow_approve_without_mount": bool(raw.get("allow_approve_without_mount", False)),
    }


def mount_extra_patterns(internal_code: str) -> dict[str, list[str]]:
    raw = get_customer_rules(internal_code).get("mount") or {}
    return {
        "smt": [str(x) for x in (raw.get("extra_smt_name_patterns") or []) if x],
        "dip": [str(x) for x in (raw.get("extra_dip_name_patterns") or []) if x],
        "assy": [str(x) for x in (raw.get("extra_assy_name_patterns") or []) if x],
    }
