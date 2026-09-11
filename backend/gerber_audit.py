"""Gerber 资料包内容审核（格式识别 + 制板层完整性）"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 制板 Gerber / 钻孔常见后缀（不含 DXF、PDF 等设计图）
GERBER_LAYER_EXTENSIONS = {
    ".gtl", ".gbl", ".gto", ".gbo", ".gtp", ".gbp", ".gts", ".gbs",
    ".gbr", ".gko", ".gm1", ".gml", ".gm2", ".apr",
    ".gdo", ".ncd", ".fab",
}
DRILL_EXTENSIONS = {".drl", ".xln", ".rou", ".txt"}
ARCHIVE_SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}

GERBER_MARKERS = (
    "%FS",
    "%MO",
    "%ADD",
    "G04",
    "G75",
    "D01",
    "D02",
    "D03",
    "M02",
    "M30",
    "%TF.",
    "%TA.",
)
EXCELLON_MARKERS = ("M48", "METRIC", "INCH", "T01", "T1", "M30", "M95", "%")


@dataclass
class GerberFileAudit:
    name: str
    size: int
    ext: str
    kind: str
    valid: bool
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "size": self.size,
            "ext": self.ext,
            "kind": self.kind,
            "valid": self.valid,
            "message": self.message,
        }


@dataclass
class GerberPackageAudit:
    status: str = "pending"
    message: str = ""
    files: list[GerberFileAudit] = field(default_factory=list)
    gerber_count: int = 0
    drill_count: int = 0
    invalid_count: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "gerber_count": self.gerber_count,
            "drill_count": self.drill_count,
            "invalid_count": self.invalid_count,
            "files": [f.to_dict() for f in self.files],
        }


def _read_head(path: Path, limit: int = 8192) -> str:
    try:
        data = path.read_bytes()[:limit]
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def _looks_like_dxf(text: str) -> bool:
    head = text.lstrip()[:400].upper()
    return head.startswith("0") and "SECTION" in head


def _looks_like_gerber(text: str) -> bool:
    upper = text.upper()
    if "%" not in upper:
        return False
    hits = sum(1 for marker in GERBER_MARKERS if marker in upper)
    return hits >= 2 or ("G04" in upper and ("D0" in upper or "M0" in upper))


def _looks_like_excellon(text: str, ext: str) -> bool:
    upper = text.upper()
    if ext in DRILL_EXTENSIONS:
        if any(marker in upper for marker in EXCELLON_MARKERS):
            return True
        if re.search(r"T\d+C", upper):
            return True
    return "M48" in upper


def _classify_file(path: Path) -> GerberFileAudit:
    ext = path.suffix.lower()
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    name = path.name
    if name.lower() in ARCHIVE_SKIP_NAMES or name.startswith("."):
        return GerberFileAudit(name=name, size=size, ext=ext, kind="skip", valid=False, message="跳过系统文件")

    text = _read_head(path)

    if _looks_like_dxf(text) or ext == ".dxf":
        return GerberFileAudit(
            name=name,
            size=size,
            ext=ext,
            kind="dxf",
            valid=False,
            message="DXF 是 CAD 图，不是 Gerber 制板文件",
        )

    if ext in {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".asm"}:
        return GerberFileAudit(
            name=name,
            size=size,
            ext=ext,
            kind="document",
            valid=False,
            message="文档/图片不是 Gerber 制板文件",
        )

    if _looks_like_excellon(text, ext):
        return GerberFileAudit(name=name, size=size, ext=ext, kind="drill", valid=True, message="钻孔文件")

    if _looks_like_gerber(text):
        return GerberFileAudit(name=name, size=size, ext=ext, kind="gerber", valid=True, message="Gerber 层文件")

    if ext in GERBER_LAYER_EXTENSIONS:
        return GerberFileAudit(
            name=name,
            size=size,
            ext=ext,
            kind="gerber",
            valid=False,
            message="后缀像 Gerber，但内容无法识别为 RS-274X",
        )

    if ext in DRILL_EXTENSIONS:
        return GerberFileAudit(
            name=name,
            size=size,
            ext=ext,
            kind="drill",
            valid=False,
            message="后缀像钻孔文件，但内容无法识别为 Excellon",
        )

    return GerberFileAudit(
        name=name,
        size=size,
        ext=ext,
        kind="unknown",
        valid=False,
        message="不是支持的 Gerber/钻孔格式",
    )


def _iter_package_files(package_dir: Path) -> list[Path]:
    files: list[Path] = []
    for item in sorted(package_dir.rglob("*")):
        if not item.is_file():
            continue
        if item.name.startswith("._"):
            continue
        files.append(item)
    return files


def audit_gerber_package(package_dir: Path) -> GerberPackageAudit:
    """审核资料包目录，返回 passed / warning / failed。"""
    result = GerberPackageAudit()
    if not package_dir.is_dir():
        result.status = "failed"
        result.message = "资料目录不存在"
        return result

    scanned = _iter_package_files(package_dir)
    if not scanned:
        result.status = "failed"
        result.message = "压缩包内没有可审核的文件"
        return result

    for path in scanned:
        audit = _classify_file(path)
        if audit.kind == "skip":
            continue
        result.files.append(audit)

    gerber_files = [f for f in result.files if f.kind == "gerber" and f.valid]
    drill_files = [f for f in result.files if f.kind == "drill" and f.valid]
    invalid_files = [f for f in result.files if not f.valid]

    result.gerber_count = len(gerber_files)
    result.drill_count = len(drill_files)
    result.invalid_count = len(invalid_files)

    if result.gerber_count == 0:
        invalid_names = "、".join(f.name for f in invalid_files[:5])
        hint = f"（{invalid_names}）" if invalid_names else ""
        result.status = "failed"
        result.message = (
            f"未找到有效 Gerber 层文件{hint}。"
            "请上传含 .gtl/.gbl/.gbr 或 Mentor .gdo 等层的制板压缩包；"
            "资料若在 *_FAB.zip 内，请直接上传 PCBA/FAB 包（系统会解嵌套）。"
            "DXF/PDF 不能代替 Gerber"
        )
        return result

    issues: list[str] = []
    if result.drill_count == 0:
        issues.append("缺少钻孔文件（.drl/.xln）")
    if invalid_files:
        bad = "、".join(f.name for f in invalid_files[:4])
        if len(invalid_files) > 4:
            bad += f" 等 {len(invalid_files)} 个"
        issues.append(f"包含非制板文件：{bad}")

    has_top = any(f.ext in {".gtl", ".gto", ".gtp", ".gts"} or "top" in f.name.lower() for f in gerber_files)
    has_bottom = any(f.ext in {".gbl", ".gbo", ".gbp", ".gbs"} or "bot" in f.name.lower() for f in gerber_files)
    if not has_top and not has_bottom and result.gerber_count == 1:
        issues.append("仅 1 个 Gerber 层，请确认是否缺面")

    if issues:
        result.status = "warning"
        result.message = "；".join(issues)
        return result

    result.status = "passed"
    layer_names = "、".join(f.name for f in gerber_files[:6])
    drill_hint = f"，钻孔 {result.drill_count} 个" if result.drill_count else ""
    result.message = f"审核通过：Gerber {result.gerber_count} 个（{layer_names}{drill_hint}）"
    return result


def audit_files_metadata(files: list[dict]) -> GerberPackageAudit:
    """根据已入库的文件元数据复审（无原始文件内容时）。"""
    result = GerberPackageAudit()
    if not files:
        result.status = "failed"
        result.message = "无文件记录"
        return result

    for item in files:
        name = str(item.get("name") or "")
        ext = str(item.get("ext") or Path(name).suffix.lower())
        size = int(item.get("size") or 0)
        kind = str(item.get("kind") or "")
        valid = item.get("valid")
        message = str(item.get("message") or "")

        if kind and valid is not None:
            result.files.append(
                GerberFileAudit(
                    name=name,
                    size=size,
                    ext=ext,
                    kind=kind,
                    valid=bool(valid),
                    message=message,
                )
            )
            continue

        if ext == ".dxf" or name.lower().endswith(".dxf"):
            result.files.append(
                GerberFileAudit(
                    name=name,
                    size=size,
                    ext=ext or ".dxf",
                    kind="dxf",
                    valid=False,
                    message="DXF 是 CAD 图，不是 Gerber 制板文件",
                )
            )
            continue

        if ext in GERBER_LAYER_EXTENSIONS:
            result.files.append(
                GerberFileAudit(
                    name=name,
                    size=size,
                    ext=ext,
                    kind="gerber",
                    valid=True,
                    message="Gerber 层文件（历史记录，未做内容复核）",
                )
            )
            continue

        if ext in DRILL_EXTENSIONS:
            result.files.append(
                GerberFileAudit(
                    name=name,
                    size=size,
                    ext=ext,
                    kind="drill",
                    valid=True,
                    message="钻孔文件（历史记录，未做内容复核）",
                )
            )
            continue

        result.files.append(
            GerberFileAudit(
                name=name,
                size=size,
                ext=ext,
                kind="unknown",
                valid=False,
                message="不是支持的 Gerber/钻孔格式",
            )
        )

    gerber_files = [f for f in result.files if f.kind == "gerber" and f.valid]
    drill_files = [f for f in result.files if f.kind == "drill" and f.valid]
    invalid_files = [f for f in result.files if not f.valid]
    result.gerber_count = len(gerber_files)
    result.drill_count = len(drill_files)
    result.invalid_count = len(invalid_files)

    if result.gerber_count == 0:
        invalid_names = "、".join(f.name for f in invalid_files[:5])
        hint = f"（{invalid_names}）" if invalid_names else ""
        result.status = "failed"
        result.message = f"未找到有效 Gerber 层文件{hint}"
        return result

    issues: list[str] = []
    if result.drill_count == 0:
        issues.append("缺少钻孔文件（.drl/.xln）")
    if invalid_files:
        bad = "、".join(f.name for f in invalid_files[:4])
        issues.append(f"包含非制板文件：{bad}")

    if issues:
        result.status = "warning" if result.gerber_count > 0 and invalid_files else "failed"
        if result.status == "failed" and result.gerber_count > 0:
            result.status = "warning"
        result.message = "；".join(issues)
        if result.gerber_count == 0:
            result.status = "failed"
        return result

    result.status = "passed"
    result.message = f"审核通过：Gerber {result.gerber_count} 个，钻孔 {result.drill_count} 个"
    return result


def audit_status_label(status: Optional[str]) -> str:
    return {
        "passed": "审核通过",
        "warning": "审核警告",
        "failed": "审核未通过",
        "pending": "待审核",
    }.get((status or "").strip(), "待审核")


def is_gerber_usable(status: Optional[str]) -> bool:
    return (status or "").strip() in ("passed", "warning")
