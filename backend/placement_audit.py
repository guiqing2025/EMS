"""贴片坐标文件审核"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from placement_parser import ParsedPlacement, parse_placement_file

PLACEMENT_ALLOWED_SUFFIXES = {".csv", ".txt", ".xlsx"}
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
GERBER_LIKE_SUFFIXES = {".gtl", ".gbl", ".gbr", ".gko", ".drl", ".gdo", ".ncd", ".dxf", ".pdf"}

FORMAT_LABELS = {
    "altium_csv": "Altium Pick&Place CSV",
    "altium_txt": "Altium Pick&Place TXT",
    "ais_txt": "AIS 坐标 TXT",
    "asc_txt": "ASC 坐标 TXT",
    "asc_xlsx": "ASC 坐标表 XLSX",
    "simple_place_txt": "简易坐标 TXT（位号 X Y 角度 封装）",
}


@dataclass
class PlacementFileAudit:
    name: str
    ext: str
    kind: str
    valid: bool
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ext": self.ext,
            "kind": self.kind,
            "valid": self.valid,
            "message": self.message,
        }


@dataclass
class PlacementPackageAudit:
    status: str = "pending"
    message: str = ""
    file_format: str = ""
    refdes_count: int = 0
    layer_count: int = 0
    files: list[PlacementFileAudit] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "file_format": self.file_format,
            "refdes_count": self.refdes_count,
            "layer_count": self.layer_count,
            "files": [f.to_dict() for f in self.files],
        }


def is_placement_usable(status: Optional[str]) -> bool:
    return (status or "").strip() in ("passed", "warning")


def audit_status_label(status: Optional[str]) -> str:
    return {
        "passed": "审核通过",
        "warning": "审核警告",
        "failed": "审核未通过",
        "pending": "待审核",
    }.get((status or "").strip(), "待审核")


def _classify_archive_file(path: Path) -> PlacementFileAudit:
    ext = path.suffix.lower()
    name = path.name
    if ext in PLACEMENT_ALLOWED_SUFFIXES:
        return PlacementFileAudit(name=name, ext=ext, kind="placement", valid=True, message="坐标候选文件")
    if ext in GERBER_LIKE_SUFFIXES:
        return PlacementFileAudit(
            name=name,
            ext=ext,
            kind="gerber_like",
            valid=False,
            message="这是制板/Gerber 类文件，不是贴片坐标",
        )
    return PlacementFileAudit(name=name, ext=ext, kind="other", valid=False, message="不是支持的坐标格式")


def audit_parsed_placement(
    parsed: ParsedPlacement,
    *,
    archive_files: Optional[list[Path]] = None,
) -> PlacementPackageAudit:
    result = PlacementPackageAudit(file_format=parsed.file_format or "unknown")
    if archive_files:
        for path in archive_files:
            item = _classify_archive_file(path)
            if item.kind != "other" or path.suffix:
                result.files.append(item)

    active_lines = [line for line in parsed.lines if line.refdes and not line.skip]
    result.refdes_count = len(active_lines)
    layers = {line.layer.strip().upper() for line in active_lines if line.layer}
    result.layer_count = len(layers)

    if result.refdes_count == 0:
        result.status = "failed"
        result.message = "无有效贴片位号，可能是基准点文件或格式错误"
        return result

    invalid_in_zip = [f for f in result.files if not f.valid]
    if invalid_in_zip and not active_lines:
        result.status = "failed"
        bad = "、".join(f.name for f in invalid_in_zip[:4])
        result.message = f"压缩包内无有效坐标文件（{bad}）"
        return result

    issues: list[str] = []
    fmt_label = FORMAT_LABELS.get(parsed.file_format or "", parsed.file_format or "未知格式")
    if parsed.file_format not in FORMAT_LABELS:
        issues.append(f"坐标格式未识别（{parsed.file_format or 'unknown'}）")

    if result.layer_count == 0:
        issues.append("位号未标注 TOP/BOT 层别，面别判定可能不准")

    top_layers = {x for x in layers if x in ("T", "TOP", "TOPLAYER")}
    bot_layers = {x for x in layers if x in ("B", "BOTTOM", "BOTTOMLAYER")}
    if layers and not top_layers and not bot_layers:
        issues.append("层别字段非常规，请确认坐标导出设置")

    if invalid_in_zip:
        bad = "、".join(f.name for f in invalid_in_zip[:3])
        issues.append(f"包内混有非坐标文件：{bad}")

    if issues:
        result.status = "warning"
        result.message = f"{fmt_label}，{result.refdes_count} 个位号；{'；'.join(issues)}"
        return result

    layer_hint = f"，含 {result.layer_count} 个层别" if result.layer_count else ""
    result.status = "passed"
    result.message = f"审核通过：{fmt_label}，{result.refdes_count} 个位号{layer_hint}"
    return result


def audit_placement_path(path: Path, *, archive_files: Optional[list[Path]] = None) -> PlacementPackageAudit:
    try:
        parsed = parse_placement_file(path)
    except ValueError as exc:
        result = PlacementPackageAudit(status="failed", message=str(exc))
        if archive_files:
            result.files = [_classify_archive_file(p) for p in archive_files if p.is_file()]
        return result
    return audit_parsed_placement(parsed, archive_files=archive_files)


def audit_placement_record(
    *,
    file_format: str,
    line_count: int,
    source_file: str = "",
) -> PlacementPackageAudit:
    """根据已入库记录复审（无原始文件时）。"""
    result = PlacementPackageAudit(file_format=file_format or "unknown", refdes_count=line_count or 0)
    if line_count <= 0 or file_format == "pending":
        result.status = "failed"
        result.message = "尚未导入有效坐标"
        return result
    if file_format not in FORMAT_LABELS:
        result.status = "warning"
        result.message = f"历史坐标记录（{file_format or 'unknown'}），{line_count} 个位号"
        return result
    fmt_label = FORMAT_LABELS[file_format]
    result.status = "passed"
    name = Path(source_file).name if source_file else ""
    hint = f"（{name}）" if name else ""
    result.message = f"审核通过：{fmt_label}，{line_count} 个位号{hint}"
    return result
