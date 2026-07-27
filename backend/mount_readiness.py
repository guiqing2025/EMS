"""工序·面别完备性检查（BOM + 坐标，不依赖 Gerber/位号图）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from models import BomLine, BomModel, PcbPlacementFile, PcbPlacementLine
from mount_classification import (
    classify_lines_mount,
    load_placement_index,
    split_refdes,
)
from material_mount_service import load_mount_overrides

READY_THRESHOLD = 0.98

ISSUE_LABELS = {
    "NO_BOM": "缺少 BOM",
    "NO_PLACEMENT": "缺少贴片坐标",
    "REF_NOT_IN_PLACEMENT": "BOM 位号在坐标中找不到",
    "NO_SIDE": "坐标缺面别（TOP/BOT）",
    "NO_PROCESS": "无法判定 SMT/DIP（缺封装且品名/主数据不足以判断）",
    "PARTIAL_SIDE": "面别不完整（部分位号无层别）",
}


@dataclass
class MountIssue:
    code: str
    severity: str
    title: str
    advice: str
    count: int = 0
    samples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "advice": self.advice,
            "count": self.count,
            "samples": self.samples[:12],
        }


def repair_ais_false_skips(db: Session, bom: BomModel) -> int:
    """修正 AIS 坐标中 Mirror=YES 被误标为 skip 的历史行。"""
    files = (
        db.query(PcbPlacementFile)
        .filter(
            PcbPlacementFile.internal_code == bom.internal_code,
            PcbPlacementFile.file_format == "ais_txt",
        )
        .all()
    )
    if not files:
        return 0
    fixed = 0
    for pf in files:
        q = db.query(PcbPlacementLine).filter(
            PcbPlacementLine.placement_file_id == pf.id,
            PcbPlacementLine.skip.is_(True),
        )
        n = q.update({"skip": False}, synchronize_session=False)
        fixed += int(n or 0)
    if fixed:
        for pf in files:
            active = (
                db.query(PcbPlacementLine)
                .filter(
                    PcbPlacementLine.placement_file_id == pf.id,
                    PcbPlacementLine.skip.is_(False),
                )
                .count()
            )
            if pf.line_count != active:
                pf.line_count = active
        db.flush()
    return fixed


def _add_issue(
    issues: dict[str, MountIssue],
    code: str,
    *,
    severity: str,
    title: str,
    advice: str,
    sample: str = "",
) -> None:
    item = issues.get(code)
    if not item:
        item = MountIssue(code=code, severity=severity, title=title, advice=advice)
        issues[code] = item
    item.count += 1
    if sample and sample not in item.samples and len(item.samples) < 20:
        item.samples.append(sample)


def check_mount_readiness(db: Session, bom_model_id: int) -> dict:
    bom = db.query(BomModel).filter(BomModel.id == bom_model_id, BomModel.is_active.is_(True)).first()
    if not bom:
        raise ValueError("机型不存在")

    repaired = repair_ais_false_skips(db, bom)

    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom.id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    issues: dict[str, MountIssue] = {}

    if not lines:
        _add_issue(
            issues,
            "NO_BOM",
            severity="block",
            title=ISSUE_LABELS["NO_BOM"],
            advice="请先导入含位号的 BOM，再检查工序与面别。",
        )
        return _pack_result(
            bom,
            ready=False,
            weld_total=0,
            precise=0,
            side_ok=0,
            process_ok=0,
            issues=issues,
            rows=[],
            repaired=repaired,
            has_placement=False,
            placement_refs=0,
            message="未导入 BOM，无法分工序分面。",
        )

    placement_index = load_placement_index(db, bom)
    has_placement = bool(placement_index)

    overrides = load_mount_overrides(db, internal_code=bom.internal_code or "")
    profile_info, mounts = classify_lines_mount(
        lines,
        placement_index=placement_index,
        profile_override=bom.mount_profile_override,
        master_overrides=overrides,
        internal_code=bom.internal_code or "",
    )
    profile_name = str((profile_info or {}).get("profile") or "")

    detail_rows: list[dict] = []
    weld_total = 0
    precise = 0
    side_ok = 0
    process_ok = 0

    for line, mount in zip(lines, mounts):
        mt = (mount.get("mount_type") or "").strip().upper()
        side = (mount.get("mount_side") or "").strip().upper()
        src = (mount.get("mount_source") or "").strip()
        reason = (mount.get("mount_reason") or "").strip()
        refs = split_refdes(line.position)

        if mt in ("ASSY", "N/A"):
            detail_rows.append(
                {
                    "line_id": line.id,
                    "material_code": line.material_code or "",
                    "material_name": line.material_name or "",
                    "position": line.position or "",
                    "mount_type": mt,
                    "mount_side": "",
                    "mount_source": src,
                    "side_precise": True,
                    "process_precise": True,
                    "row_precise": True,
                    "skipped": True,
                    "issue_codes": [],
                    "note": reason or ("装配件" if mt == "ASSY" else "非贴装件"),
                }
            )
            continue

        weld_total += 1
        row_issues: list[str] = []
        process_precise = mt in ("SMT", "DIP")
        # 无坐标时：分类结果已带工序+面别（规则/主数据/纯插件默认 TOP），则不算缺坐标
        rule_side_ok = bool(side) and process_precise

        if not has_placement:
            if not rule_side_ok:
                row_issues.append("NO_PLACEMENT")
                _add_issue(
                    issues,
                    "NO_PLACEMENT",
                    severity="block",
                    title=ISSUE_LABELS["NO_PLACEMENT"],
                    advice=(
                        "请导入贴片坐标（须含位号与 TOP/BOT），"
                        "或在 BOM 审核中确认贴装类型与面别 / 维护物料主数据。"
                        "纯插件板可先将贴装画像设为「纯插件」。"
                    ),
                    sample=line.material_code or "",
                )
                if not side:
                    row_issues.append("NO_SIDE")
                    _add_issue(
                        issues,
                        "NO_SIDE",
                        severity="block",
                        title=ISSUE_LABELS["NO_SIDE"],
                        advice="无坐标时请手补面别，或维护主数据面别；纯插件板默认 TOP。",
                        sample=line.material_code or "",
                    )
                if not process_precise:
                    row_issues.append("NO_PROCESS")
                    _add_issue(
                        issues,
                        "NO_PROCESS",
                        severity="block",
                        title=ISSUE_LABELS["NO_PROCESS"],
                        advice="请确认 SMT/DIP（审核下拉或主数据），或导入含封装的坐标。",
                        sample=line.material_code or "",
                    )
        elif refs:
            missing_refs = [r for r in refs if r not in placement_index]
            if missing_refs:
                row_issues.append("REF_NOT_IN_PLACEMENT")
                for r in missing_refs[:3]:
                    _add_issue(
                        issues,
                        "REF_NOT_IN_PLACEMENT",
                        severity="block",
                        title=ISSUE_LABELS["REF_NOT_IN_PLACEMENT"],
                        advice="核对 BOM 位号与坐标是否一致，或要求客户补全坐标。",
                        sample=r,
                    )
            else:
                sides = {
                    placement_index[r].mount_side
                    for r in refs
                    if r in placement_index and placement_index[r].mount_side
                }
                if not sides and not side:
                    row_issues.append("NO_SIDE")
                    _add_issue(
                        issues,
                        "NO_SIDE",
                        severity="block",
                        title=ISSUE_LABELS["NO_SIDE"],
                        advice="请客户重导含 Layer/Side（TOP/BOT）的坐标，或在审核中手补面别/维护主数据。",
                        sample=",".join(refs[:4]),
                    )
                elif any(not placement_index[r].mount_side for r in refs if r in placement_index) and not side:
                    row_issues.append("PARTIAL_SIDE")
                    _add_issue(
                        issues,
                        "PARTIAL_SIDE",
                        severity="warn",
                        title=ISSUE_LABELS["PARTIAL_SIDE"],
                        advice="部分位号无层别，请补全坐标面别或人工确认。",
                        sample=",".join(refs[:4]),
                    )
        else:
            if not side:
                row_issues.append("NO_SIDE")
                _add_issue(
                    issues,
                    "NO_SIDE",
                    severity="block",
                    title=ISSUE_LABELS["NO_SIDE"],
                    advice="BOM 行无位号，无法从坐标取面别；请补 BOM 位号，或维护物料主数据面别。",
                    sample=line.material_code or "",
                )

        if has_placement and not process_precise:
            row_issues.append("NO_PROCESS")
            _add_issue(
                issues,
                "NO_PROCESS",
                severity="block",
                title=ISSUE_LABELS["NO_PROCESS"],
                advice="请重导含封装(Footprint)的坐标，或写清 BOM 工艺/品名，或在物料主数据确认 SMT/DIP。",
                sample=line.material_code or (line.position or "")[:40],
            )

        side_precise = bool(side) and "NO_SIDE" not in row_issues and "REF_NOT_IN_PLACEMENT" not in row_issues
        if side_precise:
            side_ok += 1
        if process_precise:
            process_ok += 1
        row_precise = side_precise and process_precise and "NO_PLACEMENT" not in row_issues
        if row_precise:
            precise += 1

        note_parts = []
        if reason:
            note_parts.append(reason)
        for code in row_issues:
            note_parts.append(ISSUE_LABELS.get(code, code))
        detail_rows.append(
            {
                "line_id": line.id,
                "material_code": line.material_code or "",
                "material_name": line.material_name or "",
                "position": line.position or "",
                "mount_type": mt,
                "mount_side": side,
                "mount_source": src,
                "side_precise": side_precise,
                "process_precise": process_precise,
                "row_precise": row_precise,
                "skipped": False,
                "issue_codes": row_issues,
                "note": "；".join(note_parts),
            }
        )

    ratio = (precise / weld_total) if weld_total else 0.0
    unresolved = weld_total - precise
    # 有坐标：按阈值；无坐标：允许「规则/主数据/纯插件默认」已全部给出工序+面别时达标
    if has_placement:
        ready = bool(weld_total > 0 and unresolved == 0 and ratio >= READY_THRESHOLD)
    else:
        ready = bool(weld_total > 0 and unresolved == 0)

    if ready:
        if has_placement:
            message = (
                f"达标：需焊接 {weld_total} 行全部可精确分工序与面别"
                f"（面别 {side_ok}，工序 {process_ok}）。本检查仅需 BOM+坐标。"
            )
        else:
            profile_hint = f"画像={profile_name}，" if profile_name else ""
            message = (
                f"达标（无坐标）：需焊接 {weld_total} 行工序与面别已由规则/主数据判定"
                f"（{profile_hint}面别 {side_ok}，工序 {process_ok}）。"
                f"有坐标时仍建议导入以便核对。"
            )
    elif not has_placement:
        message = (
            "未导入坐标且规则/主数据未能补全全部工序与面别。"
            "纯插件板请确认贴装画像为「纯插件」，难判料在 BOM 审核中手补 SMT/DIP 与面别；"
            "或导入含 TOP/BOT 的贴片坐标。"
        )
    else:
        pct = f"{ratio * 100:.1f}%"
        message = (
            f"不达标：需焊接 {weld_total} 行中精确 {precise} 行（{pct}），"
            f"面别可用 {side_ok}，工序可用 {process_ok}。见下方缺项。"
        )

    return _pack_result(
        bom,
        ready=ready,
        weld_total=weld_total,
        precise=precise,
        side_ok=side_ok,
        process_ok=process_ok,
        issues=issues,
        rows=detail_rows,
        repaired=repaired,
        has_placement=has_placement,
        placement_refs=len(placement_index),
        message=message,
        profile_info=profile_info,
    )


def _pack_result(
    bom: BomModel,
    *,
    ready: bool,
    weld_total: int,
    precise: int,
    side_ok: int,
    process_ok: int,
    issues: dict[str, MountIssue],
    rows: list[dict],
    repaired: int,
    has_placement: bool,
    placement_refs: int,
    message: str,
    profile_info: Optional[dict] = None,
) -> dict:
    issue_list = sorted(
        issues.values(),
        key=lambda x: (0 if x.severity == "block" else 1, -x.count, x.code),
    )
    advice_lines = []
    for it in issue_list:
        samples = f"（例：{'、'.join(it.samples[:5])}）" if it.samples else ""
        advice_lines.append(f"【{it.title}】×{it.count}{samples} → {it.advice}")
    reject_text = "\n".join(advice_lines) if advice_lines else message

    return {
        "bom_model_id": bom.id,
        "internal_code": bom.internal_code or "",
        "model_code": bom.model_code or "",
        "ready": ready,
        "threshold": READY_THRESHOLD,
        "message": message,
        "reject_text": reject_text,
        "weld_total": weld_total,
        "precise_count": precise,
        "side_ok_count": side_ok,
        "process_ok_count": process_ok,
        "has_placement": has_placement,
        "placement_ref_count": placement_refs,
        "ais_skip_repaired": repaired,
        "note": "精确分工序分面仅需 BOM + 坐标；Gerber、位号图不参与本检查。",
        "detected_profile": str((profile_info or {}).get("profile") or ""),
        "issues": [i.to_dict() for i in issue_list],
        "rows": [r for r in rows if not r.get("skipped") and not r.get("row_precise")][:80],
        "all_row_count": len(rows),
    }
