"""机型资料与 BOM 关联（文件夹料号 / Excel 主件品号不一致时回退匹配）"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from models import BomModel



def normalize_code(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().upper().replace(" ", "")


def a116_code_variants(code: str) -> list[str]:
    """兼容旧名：按 A116 客户规则生成变体。"""
    return model_code_variants_for("A116", code)


def model_code_variants_for(internal_code: str, code: str) -> list[str]:
    from eng_customer_rules import get_customer_rules, resolve_model_code_variants

    return resolve_model_code_variants(code, get_customer_rules(internal_code))


def _folder_bom_model_code(folder: Path, internal_code: str) -> Optional[str]:
    from bom_excel import _latest_xlsx, parse_bom_workbook

    xlsx = _latest_xlsx(folder)
    if not xlsx:
        return None
    try:
        parsed = parse_bom_workbook(xlsx, internal_code)
        return (parsed.model_code or "").strip() or None
    except Exception:
        return None


def find_bom_for_folder(
    db: Session,
    internal_code: str,
    folder_name: str,
    *,
    folder_path: Optional[Path] = None,
    models_cache: Optional[dict[str, list[BomModel]]] = None,
) -> Optional[BomModel]:
    """Gerber/坐标/BOM 统一：按文件夹名 + 文件夹内 BOM Excel + 客户编号变体匹配机型。"""
    from asset_discovery import extract_model_key

    ic = internal_code.strip().upper()
    cache = models_cache if models_cache is not None else {}
    if ic not in cache:
        cache[ic] = (
            db.query(BomModel)
            .filter(BomModel.internal_code == ic, BomModel.is_active.is_(True))
            .all()
        )
    models = cache[ic]
    folder_key = folder_name.strip()
    model_key = extract_model_key(folder_key, ic)
    norm_key = normalize_code(model_key)

    for item in models:
        if (item.folder_name or "").strip() == folder_key:
            return item

    if folder_path and folder_path.is_dir():
        excel_code = _folder_bom_model_code(folder_path, ic)
        if excel_code:
            excel_norm = normalize_code(excel_code)
            for item in models:
                if normalize_code(item.model_code) == excel_norm:
                    return item

    search_codes = [norm_key]
    for variant in model_code_variants_for(ic, model_key):
        search_codes.append(normalize_code(variant))
    search_codes = list(dict.fromkeys(c for c in search_codes if c))

    for code in search_codes:
        for item in models:
            if normalize_code(item.model_code) == code:
                return item

    for item in models:
        mc = normalize_code(item.model_code)
        fn = normalize_code(item.folder_name or "")
        if mc and norm_key and (norm_key.startswith(mc) or mc.startswith(norm_key)):
            return item
        if fn and norm_key and (norm_key.startswith(fn) or fn.startswith(norm_key)):
            return item
        remark = item.remark or ""
        if norm_key and norm_key in remark:
            return item
        for variant in search_codes:
            if variant and variant in remark:
                return item

    return None


def folder_alias_note(folder_name: str, internal_code: str, model_code: str) -> Optional[str]:
    from asset_discovery import extract_model_key

    folder_key = extract_model_key(folder_name, internal_code)
    if not folder_key or folder_key == model_code:
        return None
    return f"资料夹料号:{folder_key}"


def merge_remark(existing: Optional[str], note: str) -> str:
    text = (existing or "").strip()
    if not text:
        return note
    if note in text:
        return text
    return f"{text};{note}"
