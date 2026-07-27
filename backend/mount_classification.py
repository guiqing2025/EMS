"""根据贴片坐标 + 规则 + 物料主数据，判定 BOM 物料贴装类型与面别"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from models import BomLine, BomModel, PcbPlacementFile, PcbPlacementLine
from mount_type import (
    classify_footprint_mount,
    classify_mount_type,
    infer_mount_from_refdes,
    is_non_mount_line,
    is_pcb_line,
    resolve_assembly_profile,
)
from placement_canonical import pick_canonical_placement

_REF_SPLIT = re.compile(r"[,;\s/]+")
# 粘连位号：H1H2、R10R11（字母前缀+数字，从左贪心切开）
_REF_ATOM = re.compile(r"([A-Z]+\d+)", re.I)
VALID_MOUNT_TYPES = frozenset({"SMT", "DIP", "ASSY", "N/A"})


@dataclass
class PlacementRefInfo:
    mount_type: str
    mount_side: str
    footprint: str = ""


def _explode_glued_refdes(part: str) -> Optional[list[str]]:
    """将 H1H2 拆成 [H1, H2]；无法完整切开则返回 None。"""
    text = part.strip().upper()
    if not text:
        return None
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        m = _REF_ATOM.match(text, pos)
        if not m:
            return None
        tokens.append(m.group(1).upper())
        pos = m.end()
    return tokens if len(tokens) >= 2 else None


def split_refdes(position: Optional[str]) -> list[str]:
    """拆分 BOM 位号列。支持逗号/空格分隔，以及 H1H2 这类粘连写法。"""
    if not position:
        return []
    out: list[str] = []
    for chunk in _REF_SPLIT.split(str(position)):
        part = chunk.strip().upper()
        if not part:
            continue
        glued = _explode_glued_refdes(part)
        if glued:
            out.extend(glued)
        else:
            out.append(part)
    return out


def normalize_layer(layer: Optional[str]) -> Optional[str]:
    if not layer:
        return None
    text = str(layer).strip().upper()
    if text in ("T", "TOP", "TOPLAYER"):
        return "TOP"
    if text in ("B", "BOTTOM", "BOTTOMLAYER"):
        return "BOT"
    return None


def _combine_layers(layers: set[str]) -> str:
    valid = {x for x in layers if x in ("TOP", "BOT")}
    if not valid:
        return ""
    if valid == {"TOP"}:
        return "TOP"
    if valid == {"BOT"}:
        return "BOT"
    return "TOP+BOT"


def _norm_mat_code(code: Optional[str]) -> str:
    from engineering_service import normalize_code

    return normalize_code(code or "")


def load_placement_index(db: Session, bom: BomModel) -> dict[str, PlacementRefInfo]:
    """位号 -> 贴装类型与面别（来自坐标文件封装 + 层别，非 Gerber）。"""
    from eng_asset_scope import assets_scope_for, find_assets_for_bom
    from engineering_service import normalize_code

    if assets_scope_for(bom.internal_code or "") == "order":
        place, _, _ = find_assets_for_bom(db, bom)
        if not place:
            return {}
        file_ids = [place.id]
    else:
        candidates = (
            db.query(PcbPlacementFile)
            .filter(PcbPlacementFile.internal_code == bom.internal_code)
            .all()
        )
        if not candidates:
            return {}

        model_norm = normalize_code(bom.model_code)
        file_ids = []
        for item in candidates:
            if item.bom_model_id == bom.id:
                file_ids.append(item.id)
                continue
            item_norm = normalize_code(item.model_code)
            if item_norm == model_norm:
                file_ids.append(item.id)
                continue
            prefix = model_norm[:8] if len(model_norm) >= 8 else model_norm
            if prefix and (
                item_norm.startswith(prefix)
                or model_norm.startswith(item_norm[:8] if len(item_norm) >= 8 else item_norm)
            ):
                file_ids.append(item.id)

        file_ids = list(dict.fromkeys(file_ids))
        if not file_ids:
            return {}

    files = db.query(PcbPlacementFile).filter(PcbPlacementFile.id.in_(file_ids)).all()
    canonical = pick_canonical_placement(files)
    if not canonical:
        return {}

    rows = (
        db.query(
            PcbPlacementLine.refdes,
            PcbPlacementLine.layer,
            PcbPlacementLine.footprint,
            PcbPlacementLine.material_hint,
            PcbPlacementLine.skip,
        )
        .filter(PcbPlacementLine.placement_file_id == canonical.id)
        .all()
    )

    index: dict[str, PlacementRefInfo] = {}
    for refdes, layer, footprint, material_hint, skipped in rows:
        if not refdes:
            continue
        key = refdes.strip().upper()
        side = normalize_layer(layer) or ""
        if not side and footprint:
            side = normalize_layer(footprint) or ""
        # AIS 历史数据曾把 Mirror=YES 误存为 skip；有面别的行仍参与分工序分面
        treat_skip = bool(skipped) and not side
        fp_mount = "" if treat_skip else classify_footprint_mount(footprint, material_hint)
        index[key] = PlacementRefInfo(
            mount_type=fp_mount,
            mount_side=side,
            footprint=(footprint or material_hint or "").strip(),
        )
    return index


def load_placement_map(db: Session, bom: BomModel) -> dict[str, str]:
    """兼容旧接口：仅返回 SMT 位号的面别。"""
    index = load_placement_index(db, bom)
    return {
        ref: info.mount_side
        for ref, info in index.items()
        if info.mount_type == "SMT" and info.mount_side
    }


def _result(mount_type: str, mount_side: str, mount_source: str, mount_reason: str = "") -> dict[str, str]:
    if mount_type in ("ASSY", "N/A"):
        return {
            "mount_type": mount_type,
            "mount_side": "",
            "mount_source": mount_source,
            "mount_reason": mount_reason or (
                "装配五金，非 SMT/DIP 焊接工序" if mount_type == "ASSY" else "非贴装件（光板/标签/软件等）"
            ),
        }
    return {
        "mount_type": mount_type,
        "mount_side": mount_side,
        "mount_source": mount_source,
        "mount_reason": mount_reason,
    }


def _normalize_master_side(mount_side: Optional[str]) -> str:
    side = (mount_side or "").strip().upper()
    if side in ("TOP", "BOT", "TOP+BOT"):
        return side
    return ""


def classify_line_mount(
    line: BomLine,
    placement_index: Optional[dict[str, PlacementRefInfo]] = None,
    placement_map: Optional[dict[str, str]] = None,
    assembly_profile: Optional[str] = None,
    master_type: Optional[str] = None,
    master_side: Optional[str] = None,
    extra_smt_patterns: Optional[tuple] = None,
    extra_dip_patterns: Optional[tuple] = None,
    extra_assy_patterns: Optional[tuple] = None,
) -> dict[str, str]:
    """
    返回 mount_type(SMT/DIP/ASSY/N/A/空)、mount_side、mount_source(master/placement/rule/空)
    优先级：BOM 工艺列 → 物料主数据 → 坐标+规则 → 位号前缀 → 整机画像兜底
    物料主数据中的面别（人工修正）优先于坐标推断。
    """
    if placement_index is None and placement_map is not None:
        placement_index = {
            ref: PlacementRefInfo(mount_type="SMT", mount_side=side)
            for ref, side in placement_map.items()
        }

    refs = split_refdes(line.position)
    confirmed_side = _normalize_master_side(master_side)

    # 工艺列优先（classify_mount_type 已读 process）
    rule_type = classify_mount_type(
        process=line.process,
        material_name=line.material_name,
        spec=line.spec,
        extra_smt_patterns=extra_smt_patterns,
        extra_dip_patterns=extra_dip_patterns,
        extra_assy_patterns=extra_assy_patterns,
    )
    if (line.process or "").strip() and rule_type in VALID_MOUNT_TYPES:
        side = confirmed_side
        if not side:
            if rule_type == "DIP" and placement_index and refs:
                layers = {placement_index[r].mount_side for r in refs if r in placement_index and placement_index[r].mount_side}
                side = _combine_layers(layers) or ("TOP" if assembly_profile == "dip_only" else "")
            elif rule_type == "SMT" and placement_index and refs:
                layers = {placement_index[r].mount_side for r in refs if r in placement_index and placement_index[r].mount_side}
                side = _combine_layers(layers)
            elif rule_type == "DIP" and assembly_profile == "dip_only":
                side = "TOP"
        src = "master" if confirmed_side else "rule"
        reason = "物料主数据已确认面别" if confirmed_side else "来自 BOM 工艺列"
        return _result(rule_type, side, src, reason)

    master = (master_type or "").strip().upper()
    if master in VALID_MOUNT_TYPES:
        side = confirmed_side
        if not side and master in ("SMT", "DIP") and placement_index and refs:
            layers = {
                placement_index[r].mount_side
                for r in refs
                if r in placement_index and placement_index[r].mount_side
            }
            side = _combine_layers(layers)
            if master == "DIP" and not side and assembly_profile == "dip_only":
                side = "TOP"
        return _result(master, side, "master", "物料主数据已确认")

    if is_pcb_line(material_name=line.material_name, material_code=line.material_code):
        return _result("N/A", "", "rule", "印制板/光板，非贴装件")
    if is_non_mount_line(material_name=line.material_name) or rule_type == "N/A":
        return _result("N/A", "", "rule", "标签/软件等非贴装件")
    if rule_type == "ASSY":
        return _result("ASSY", "", "rule", "品名/规格判定为装配五金")

    if placement_index and refs:
        mount_types: list[str] = []
        smt_layers: set[str] = set()
        dip_layers: set[str] = set()
        for ref in refs:
            info = placement_index.get(ref)
            if info:
                fp_type = classify_footprint_mount(info.footprint, info.footprint) if info.footprint else ""
                mt = info.mount_type or fp_type or rule_type or ""
                if mt in ("ASSY", "N/A"):
                    mount_types.append(mt)
                    continue
                if mt:
                    mount_types.append(mt)
                if info.mount_side:
                    if mt == "SMT" or (not mt and rule_type not in ("DIP", "ASSY")):
                        side = info.mount_side
                        if side == "TOP+BOT":
                            smt_layers.update({"TOP", "BOT"})
                        elif side:
                            smt_layers.add(side)
                    elif mt == "DIP" or rule_type == "DIP":
                        side = info.mount_side
                        if side == "TOP+BOT":
                            dip_layers.update({"TOP", "BOT"})
                        elif side:
                            dip_layers.add(side)
            elif rule_type:
                mount_types.append(rule_type)

        if mount_types:
            if any(m == "ASSY" for m in mount_types) and not any(m in ("SMT", "DIP") for m in mount_types):
                return _result("ASSY", "", "placement")
            smt_count = sum(1 for m in mount_types if m == "SMT")
            dip_count = sum(1 for m in mount_types if m == "DIP")
            if smt_count > 0 and dip_count == 0:
                return _result("SMT", _combine_layers(smt_layers), "placement")
            if dip_count > 0 and smt_count == 0:
                return _result("DIP", _combine_layers(dip_layers), "placement")
            if dip_count > 0:
                return _result("DIP", _combine_layers(dip_layers or smt_layers), "placement")
        elif refs and any(placement_index.get(ref) for ref in refs):
            layers: set[str] = set()
            for ref in refs:
                info = placement_index.get(ref)
                if info and info.mount_side:
                    if info.mount_side == "TOP+BOT":
                        layers.update({"TOP", "BOT"})
                    else:
                        layers.add(info.mount_side)
            side = _combine_layers(layers)
            inferred = rule_type
            if not inferred:
                for ref in refs:
                    info = placement_index.get(ref)
                    if not info or not info.footprint:
                        continue
                    inferred = classify_footprint_mount(info.footprint, info.footprint)
                    if inferred:
                        break
            if not inferred:
                inferred = infer_mount_from_refdes(line.position)
            if inferred:
                src = "placement" if inferred in ("SMT", "DIP") and side else "rule"
                if inferred == "DIP" and side:
                    src = "placement"
                return _result(
                    inferred,
                    side if inferred in ("SMT", "DIP") else "",
                    src,
                    "坐标有位号；封装/规则推断",
                )

    if rule_type in ("SMT", "DIP"):
        side = ""
        if rule_type == "DIP" and assembly_profile == "dip_only":
            side = "TOP"
        elif rule_type in ("SMT", "DIP") and placement_index and refs:
            layers = {
                placement_index[r].mount_side
                for r in refs
                if r in placement_index and placement_index[r].mount_side
            }
            side = _combine_layers(layers)
        return _result(rule_type, side, "rule", "品名/规格规则推断")

    ref_guess = infer_mount_from_refdes(line.position)
    if ref_guess:
        side = ""
        if placement_index and refs:
            layers = {
                placement_index[r].mount_side
                for r in refs
                if r in placement_index and placement_index[r].mount_side
            }
            side = _combine_layers(layers)
        if not side and assembly_profile == "dip_only":
            side = "TOP"
        return _result(ref_guess, side, "rule", "按位号前缀推断为插件(DIP)")

    if assembly_profile == "dip_only" and refs and not is_non_mount_line(material_name=line.material_name):
        return _result("DIP", "TOP", "rule", "整机贴装画像为纯插件")

    if assembly_profile == "smt_only" and refs and not is_non_mount_line(material_name=line.material_name):
        return _result("SMT", "TOP", "rule", "整机贴装画像为纯贴片")

    # 未识别：给出可读原因
    reasons = []
    if not refs:
        reasons.append("无位号")
    elif not placement_index:
        reasons.append("本机型未导入坐标")
    elif not any(placement_index.get(r) for r in refs):
        reasons.append("坐标中无对应位号")
    else:
        reasons.append("坐标有位号但封装无法识别 SMT/DIP")
    if not rule_type:
        reasons.append("品名/规格无特征且无物料主数据")
    return {
        "mount_type": "",
        "mount_side": "",
        "mount_source": "",
        "mount_reason": "；".join(reasons) or "无法判定贴装类型",
    }


def _split_master_override(entry) -> tuple[str, str]:
    """兼容旧格式（仅类型字符串）与新格式 {mount_type, mount_side}。"""
    if isinstance(entry, dict):
        return (
            str(entry.get("mount_type") or "").strip().upper(),
            _normalize_master_side(entry.get("mount_side")),
        )
    if isinstance(entry, str):
        return entry.strip().upper(), ""
    return "", ""


def classify_lines_mount(
    lines: list[BomLine],
    placement_index: Optional[dict[str, PlacementRefInfo]] = None,
    profile_override: Optional[str] = None,
    master_overrides: Optional[dict] = None,
    internal_code: str = "",
) -> tuple[dict[str, object], list[dict[str, str]]]:
    """批量判定 BOM 行贴装信息，并返回整机贴装画像。"""
    from eng_customer_rules import mount_extra_patterns

    extras = mount_extra_patterns(internal_code) if internal_code else {"smt": [], "dip": [], "assy": []}
    extra_smt = tuple(extras.get("smt") or ())
    extra_dip = tuple(extras.get("dip") or ())
    extra_assy = tuple(extras.get("assy") or ())
    profile_info = resolve_assembly_profile(lines, profile_override)
    profile = str(profile_info.get("profile") or "unknown")
    overrides = master_overrides or {}
    mounts = []
    for line in lines:
        key = _norm_mat_code(line.material_code)
        entry = overrides.get(key) or overrides.get((line.material_code or "").strip().upper())
        master_type, master_side = _split_master_override(entry)
        mounts.append(
            classify_line_mount(
                line,
                placement_index=placement_index,
                assembly_profile=profile,
                master_type=master_type,
                master_side=master_side,
                extra_smt_patterns=extra_smt,
                extra_dip_patterns=extra_dip,
                extra_assy_patterns=extra_assy,
            )
        )
    return profile_info, mounts


def mount_for_line(
    db: Session,
    bom: BomModel,
    line: BomLine,
    lines: Optional[list[BomLine]] = None,
    placement_index: Optional[dict[str, PlacementRefInfo]] = None,
) -> dict[str, str]:
    from material_mount_service import load_mount_overrides

    if lines is None:
        lines = (
            db.query(BomLine)
            .filter(BomLine.bom_model_id == bom.id)
            .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
            .all()
        )
    if placement_index is None:
        placement_index = load_placement_index(db, bom)
    overrides = load_mount_overrides(db, internal_code=bom.internal_code or "")
    _, mounts = classify_lines_mount(
        lines,
        placement_index=placement_index,
        profile_override=bom.mount_profile_override,
        master_overrides=overrides,
        internal_code=bom.internal_code or "",
    )
    for row, mount in zip(lines, mounts):
        if row.id == line.id:
            return mount
    master_type, master_side = _split_master_override(
        overrides.get(_norm_mat_code(line.material_code))
    )
    return classify_line_mount(
        line,
        placement_index=placement_index,
        assembly_profile=str(
            resolve_assembly_profile(lines, bom.mount_profile_override).get("profile") or "unknown"
        ),
        master_type=master_type,
        master_side=master_side,
    )


def enrich_line_mount(db: Session, bom: BomModel, line: BomLine, placement_map: Optional[dict[str, str]] = None) -> dict:
    return mount_for_line(db, bom, line)
