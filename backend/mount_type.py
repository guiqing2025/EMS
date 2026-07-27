"""BOM 物料贴装类型（SMT / DIP）识别"""
from __future__ import annotations

import re
from typing import Optional

SMT_NAME_PATTERNS = ("贴片", "SMT", "表贴")
DIP_NAME_PATTERNS = (
    "直插",
    "插件",
    "排针",
    "排母",
    "插针",
    "牛角座",
    "端子台",
    "继电器",
    "线组",
    "排线",
    "模块电源",
    "二次模块",
    "放电管",
    "晶闸管",
    "压敏",
    "跳线",
    "温感电阻",
    "正温度系数",
    "导电体",
    "功率端子",
    "金属插脚",
    "插脚",
)

# 装配五金：不算 SMT/DIP 焊接工序
ASSY_NAME_PATTERNS = (
    "标准件",
    "螺栓",
    "螺母",
    "垫片",
    "垫圈",
    "螺丝",
    "弹簧垫",
    "介子",
    "卡簧",
    "铆钉",
)

ASSY_SPEC_PATTERNS = (
    "GB9074",
    "GB/T",
    "外六角",
    "十字凹穴",
    "达克罗",
    "M3*",
    "M4*",
    "M5*",
    "M6*",
    "M8*",
    "M10*",
)

POWER_CONNECTOR_PATTERNS = (
    "功率端子",
    "金属功率端子",
    "金属插脚",
    "插脚",
    "导电体",
    "脚间距",
    "PIN间距",
)

# 位号前缀 → 默认 DIP（无 SMT 封装、且非装配件时）
DIP_REFDES_PREFIXES = (
    "J",
    "CN",
    "CON",
    "TB",
    "JK",
)

SMT_SPEC_PATTERNS = (
    "SMD",
    "SOT-",
    "SOT23",
    "SOIC",
    "SO-",
    "TQFP",
    "QFP",
    "LQFP",
    "BGA",
    "QFN",
    "DFN",
    "MSOP",
    "SSOP",
    "TSSOP",
    "SOP8",
    "SOP-8",
    "SOP-",
    "SOP",
    "SON",
    "WSON",
    "SMA",
    "SMB",
    "SMC",
    "SOD-",
    "TO-263",
    "TO-252",
    "DUB-",
    "SO POWERPAD",
    "0603",
    "0805",
    "1206",
    "0402",
    "0201",
)

DIP_SPEC_PATTERNS = (
    "DIP-",
    "DIP ",
    "DIP4",
    "THT",
    "AXIAL",
    "插件插座",
    "TH ",
    "通孔焊接",
    "通孔",
    "直针",
    "1/4W",
    "1/2W",
    "1/8W",
    "2WS",
    "3WS",
    "5WS",
    "1WS",
    "TO-247",
    "TO247",
    "TO-264",
    "TO264",
    "SIP",
    "_SIP",
)

BOARD_DIP_SPEC_PATTERNS = (
    "通孔焊接",
    "通孔",
    "插件板",
    "纯插件",
    "THT",
)

THROUGH_HOLE_COMPONENT_PATTERNS = (
    "φ3",
    "Φ3",
    "φ5",
    "Φ5",
    "1/4W",
    "1/2W",
    "1/8W",
    "2WS",
    "3WS",
    "5WS",
    "1WS",
    "直针",
)

FOOTPRINT_DIP_PATTERNS = (
    "DIP",
    "THT",
    "PTH",
    "THRU",
    "AXIAL",
    "JP",
    "HDR",
    "HEADER",
    "PINHDR",
    "RJ45",
    "RJ-",
    "LED-5",
    "LED5MM",
    "LED3MM",
    "TO-220",
    "TO220",
    "TO-247",
    "TO247",
    "TO-264",
    "TO264",
    "SPACER",
    "POST",
    "BOLT",
    "CAP2",
    "CAPC2",
    "ERB",
    "TEB",
    "R2WH",
    "R2W",
    "BAR-",
    "P7.5",
    "DC-7P",
    "PAD-NH",
)

FOOTPRINT_SMT_PATTERNS = (
    "0402",
    "0603",
    "0805",
    "1206",
    "0201",
    "SOT",
    "QFN",
    "QFP",
    "BGA",
    "SOIC",
    "DFN",
    "MSOP",
    "SSOP",
    "TSSOP",
    "SON",
    "WSON",
    "SMA",
    "SMB",
    "SMC",
    "SOD",
    "SC0603",
    "SC0805",
    "SC1206",
    "R0603",
    "C0603",
    "L0603",
    "2512",
    "SR2512",
    "TO-252",
    "XTAL-SMD",
)

OTHER_NAME_PATTERNS = ("光板", "PCB", "标签", "软件", "软件包", "烧录")


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    upper = text.upper()
    for p in patterns:
        if p.upper() in upper:
            return True
    return False


def _is_connector_dip(name: str, spec: str) -> bool:
    blob = f"{name} {spec}"
    if "贴片" in name:
        return False
    if any(k in name for k in ("插座", "端子", "连接器", "排针", "排母")):
        return True
    if re.search(r"XH\s*[\d.]|PH\s*[\d.]|PH\d", blob, re.I):
        return True
    return False


def classify_ais_material_hint(material_hint: Optional[str] = None) -> str:
    """AIS 坐标文件中的数字料站/封装码（如 14050063、08070504）。"""
    code = (material_hint or "").strip()
    if not code.isdigit() or len(code) < 4:
        return ""
    if code.startswith(("1405", "1406", "1410")):
        return "DIP"
    if code.startswith("1408"):
        return "DIP"
    if code.startswith(("07", "08", "15", "38", "39")):
        return "SMT"
    return ""


def classify_footprint_mount(
    footprint: Optional[str] = None,
    material_hint: Optional[str] = None,
) -> str:
    """根据坐标文件中的封装名判定 SMT / DIP。"""
    fp = (footprint or material_hint or "").strip().upper()
    if not fp:
        return ""
    ais = classify_ais_material_hint(material_hint or footprint)
    if ais:
        return ais
    if _contains_any(fp, FOOTPRINT_DIP_PATTERNS):
        return "DIP"
    if re.search(r"(^|[^A-Z])JP\d", fp):
        return "DIP"
    if _contains_any(fp, FOOTPRINT_SMT_PATTERNS):
        return "SMT"
    return ""


def classify_mount_type(
    *,
    process: Optional[str] = None,
    material_name: Optional[str] = None,
    spec: Optional[str] = None,
    extra_smt_patterns: Optional[tuple] = None,
    extra_dip_patterns: Optional[tuple] = None,
    extra_assy_patterns: Optional[tuple] = None,
) -> str:
    """
    返回 SMT / DIP / ASSY / N/A / 空字符串。
    优先 BOM 工艺列，其次品名/规格（功率连接 > 装配五金 > SMT/DIP 特征）。
    可通过 extra_*_patterns 叠加客户专属关键词。
    """
    name = (material_name or "").strip()
    spec_text = (spec or "").strip()
    proc = (process or "").strip().upper()
    blob = f"{name} {spec_text}"
    smt_names = SMT_NAME_PATTERNS + tuple(extra_smt_patterns or ())
    dip_names = DIP_NAME_PATTERNS + tuple(extra_dip_patterns or ())
    assy_names = ASSY_NAME_PATTERNS + tuple(extra_assy_patterns or ())

    if proc:
        if "SMT" in proc or "贴片" in proc:
            return "SMT"
        if "插件" in proc or "DIP" in proc or "THT" in proc or "波峰" in proc:
            return "DIP"
        if "ASSY" in proc or "装配" in proc or "五金" in proc:
            return "ASSY"
        if "N/A" in proc or "非贴装" in proc:
            return "N/A"

    if name and _contains_any(name, OTHER_NAME_PATTERNS):
        return "N/A"
    if is_pcb_line(material_name=name):
        return "N/A"

    # 功率端子 / 插脚等优先于「小五金」泛称
    if _contains_any(blob, POWER_CONNECTOR_PATTERNS):
        return "DIP"
    if re.search(r"\b\d+\s*PIN\b|\d+PIN|脚间距", blob, re.I):
        return "DIP"

    if name and _contains_any(name, assy_names):
        return "ASSY"
    if "小五金" in name and not _contains_any(blob, SMT_SPEC_PATTERNS):
        return "ASSY"
    if spec_text and _contains_any(spec_text, ASSY_SPEC_PATTERNS) and (
        name and ("标准件" in name or "五金" in name or "螺栓" in name or "螺丝" in name)
    ):
        return "ASSY"

    if name and _contains_any(name, smt_names):
        return "SMT"
    if spec_text and _contains_any(spec_text, ("贴片", "表贴")):
        return "SMT"
    if name and _contains_any(name, dip_names):
        return "DIP"
    if name and "安规" in name:
        return "DIP"
    if name and "保险" in name:
        return "DIP"

    if spec_text and _contains_any(spec_text, SMT_SPEC_PATTERNS):
        return "SMT"
    if spec_text and _contains_any(spec_text, DIP_SPEC_PATTERNS):
        return "DIP"
    # 规格末尾或独立词「DIP」（如跳线规格 ...镀锡,DIP），避免误伤含 DIP 的其它词前缀
    if spec_text and re.search(r"(?<![A-Za-z0-9])DIP(?![A-Za-z0-9])", spec_text, re.I):
        return "DIP"
    if name and re.search(r"(?<![A-Za-z0-9])PTC(?![A-Za-z0-9])", name, re.I):
        return "DIP"
    if spec_text and "Y2" in spec_text.upper():
        return "DIP"

    if _is_connector_dip(name, spec_text):
        return "DIP"

    if "电解" in name:
        if _contains_any(blob, ("SMD", "贴片")):
            return "SMT"
        return "DIP"

    if name and any(k in name for k in ("二极管", "三极管", "MOS", "稳压", "TVS", "LED", "芯片", "IC", "光耦", "电感")):
        if _contains_any(blob, SMT_SPEC_PATTERNS):
            return "SMT"
        if any(k in name for k in ("三极管", "二极管", "MOS")):
            return "DIP"
        if "LED" in name and _contains_any(blob, THROUGH_HOLE_COMPONENT_PATTERNS):
            return "DIP"

    if name and "电阻" in name and _contains_any(blob, THROUGH_HOLE_COMPONENT_PATTERNS):
        return "DIP"

    return ""


def infer_mount_from_refdes(position: Optional[str] = None) -> str:
    """位号前缀启发式：连接器类默认 DIP。"""
    if not position:
        return ""
    refs = [p.strip().upper() for p in re.split(r"[,;\s]+", position) if p.strip()]
    if not refs:
        return ""
    dip_like = 0
    for ref in refs:
        for prefix in DIP_REFDES_PREFIXES:
            if ref == prefix or ref.startswith(prefix) and (
                len(ref) == len(prefix) or ref[len(prefix) : len(prefix) + 1].isdigit()
            ):
                dip_like += 1
                break
    if dip_like and dip_like == len(refs):
        return "DIP"
    return ""


def is_pcb_line(*, material_name: Optional[str] = None, material_code: Optional[str] = None) -> bool:
    name = (material_name or "").strip()
    code = (material_code or "").strip()
    if name and _contains_any(name, ("光板", "PCB", "印制板", "制成板")):
        return True
    if code and code.startswith("03"):
        return True
    return False


def is_non_mount_line(*, material_name: Optional[str] = None) -> bool:
    name = (material_name or "").strip()
    return bool(name and _contains_any(name, OTHER_NAME_PATTERNS))


def detect_assembly_profile(
    lines: list,
) -> dict[str, object]:
    """
    仅根据 BOM 行判定整机贴装画像：dip_only / smt_only / mixed / unknown。
    不依赖贴片坐标；用于纯插件板等无坐标场景。
    """
    smt_score = 0
    dip_score = 0
    reasons: list[str] = []
    mountable_refs = 0

    for line in lines:
        name = (line.material_name or "").strip()
        spec = (line.spec or "").strip()
        proc = (line.process or "").strip()
        position = (line.position or "").strip()
        blob = f"{name} {spec}"

        if is_pcb_line(material_name=name, material_code=line.material_code):
            if _contains_any(blob, BOARD_DIP_SPEC_PATTERNS):
                dip_score += 3
                reasons.append("PCB 规格含通孔/插件特征")
            continue

        if is_non_mount_line(material_name=name):
            continue

        if position:
            mountable_refs += 1

        if proc:
            upper = proc.upper()
            if "SMT" in upper or "贴片" in proc:
                smt_score += 2
            elif "插件" in proc or "DIP" in upper or "THT" in upper or "波峰" in proc:
                dip_score += 2

        rule_type = classify_mount_type(process=proc or None, material_name=name or None, spec=spec or None)
        if rule_type in ("ASSY", "N/A"):
            continue
        if rule_type == "SMT":
            smt_score += 2
        elif rule_type == "DIP":
            dip_score += 2

        if _contains_any(blob, SMT_SPEC_PATTERNS) or _contains_any(name, SMT_NAME_PATTERNS):
            smt_score += 1
        if _contains_any(blob, DIP_SPEC_PATTERNS + THROUGH_HOLE_COMPONENT_PATTERNS + POWER_CONNECTOR_PATTERNS):
            dip_score += 1

    if smt_score > 0 and dip_score == 0:
        return {"profile": "smt_only", "confidence": "high", "reasons": reasons}
    if dip_score > 0 and smt_score == 0:
        confidence = "high" if dip_score >= 3 else "medium"
        return {"profile": "dip_only", "confidence": confidence, "reasons": reasons}
    if smt_score > 0 and dip_score > 0:
        return {"profile": "mixed", "confidence": "high", "reasons": reasons}
    if mountable_refs > 0 and smt_score == 0:
        reasons.append("存在位号但无 SMT 特征")
        return {"profile": "dip_only", "confidence": "low", "reasons": reasons}
    return {"profile": "unknown", "confidence": "low", "reasons": reasons}


MOUNT_PROFILE_OVERRIDES = frozenset({"dip_only", "smt_only", "mixed"})


def resolve_assembly_profile(
    lines: list,
    profile_override: Optional[str] = None,
) -> dict[str, object]:
    """合并手工贴装画像与自动识别结果。"""
    override = (profile_override or "").strip()
    if override in MOUNT_PROFILE_OVERRIDES:
        return {
            "profile": override,
            "confidence": "manual",
            "reasons": ["手工指定贴装画像"],
            "source": "manual",
        }
    detected = detect_assembly_profile(lines)
    detected["source"] = "auto"
    return detected
