"""工程资料与 BOM 覆盖情况检查（不依赖本地共享盘）。"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from asset_discovery import extract_model_key
from engineering_service import normalize_code
from model_linkage import find_bom_for_folder
from models import BomModel, PcbGerberPackage, PcbPlacementFile

logger = logging.getLogger(__name__)


def _asset_status(row, *, ready_field: str) -> str:
    if ready_field == "file_count":
        return "ready" if (row.file_count or 0) > 0 else "pending"
    return "ready" if (row.line_count or 0) > 0 else "pending"


def scan_asset_bom_gaps(db: Session) -> dict:
    """统计：有 Gerber/坐标但缺 BOM，或资料夹料号与 BOM 料号不一致。

    不再扫描本地工程共享盘；BOM / 坐标 / Gerber 均以库内人工导入记录为准。
    """
    boms = db.query(BomModel).filter(BomModel.is_active.is_(True)).all()
    bom_by_code = {(b.internal_code, normalize_code(b.model_code)): b for b in boms}

    missing_bom: list[dict] = []
    code_mismatch: list[dict] = []
    seen_missing: set[tuple[str, str, str]] = set()

    def inspect(internal_code: str, model_code: str, folder_name: str, asset_type: str, asset_status: str, asset_id: int):
        ic = internal_code.strip().upper()
        folder_key = extract_model_key(folder_name or model_code, ic)
        bom = bom_by_code.get((ic, normalize_code(model_code)))
        if not bom and folder_key:
            bom = bom_by_code.get((ic, normalize_code(folder_key)))
        if bom:
            if folder_key and normalize_code(bom.model_code) != normalize_code(folder_key):
                code_mismatch.append({
                    "internal_code": ic,
                    "folder_key": folder_key,
                    "folder_name": folder_name,
                    "asset_model_code": model_code,
                    "bom_model_code": bom.model_code,
                    "bom_model_id": bom.id,
                    "asset_type": asset_type,
                    "asset_status": asset_status,
                    "asset_id": asset_id,
                    "hint": f"资料夹料号 {folder_key}，BOM 料号 {bom.model_code}",
                })
            return
        key = (ic, model_code, folder_name or "")
        if key in seen_missing:
            return
        seen_missing.add(key)
        missing_bom.append({
            "internal_code": ic,
            "folder_key": folder_key,
            "folder_name": folder_name,
            "asset_model_code": model_code,
            "asset_type": asset_type,
            "asset_status": asset_status,
            "asset_id": asset_id,
            "hint": "有工程资料但 BOM 机型列表中无对应料号",
        })

    for row in db.query(PcbGerberPackage).all():
        status = _asset_status(row, ready_field="file_count")
        if status != "ready":
            continue
        inspect(row.internal_code, row.model_code, row.folder_name or "", "gerber", status, row.id)

    for row in db.query(PcbPlacementFile).all():
        status = "ready" if row.line_count > 0 else "pending"
        inspect(row.internal_code, row.model_code, row.folder_name or "", "placement", status, row.id)

    missing_bom.sort(key=lambda x: (x["internal_code"], x["folder_key"]))
    code_mismatch.sort(key=lambda x: (x["internal_code"], x["folder_key"]))

    return {
        "missing_bom_count": len(missing_bom),
        "code_mismatch_count": len(code_mismatch),
        "missing_bom": missing_bom[:200],
        "code_mismatch": code_mismatch[:200],
    }


def relink_asset_records(db: Session) -> dict:
    """回填 Gerber/坐标的 bom_model_id，并将 model_code 对齐到 BOM 主件品号。

    仅按库内订单号 / 机型匹配，不扫描本地工程共享盘。
    """
    from config import get_engineering_customers
    from eng_asset_scope import assets_scope_for

    updated = 0
    models_cache: dict[str, list[BomModel]] = {}

    def _resolve_bom(ic: str, row, folder: Optional[object] = None):
        bom = find_bom_for_folder(
            db,
            ic,
            row.folder_name or row.model_code,
            folder_path=None,
            models_cache=models_cache,
        )
        if not bom:
            return None
        if assets_scope_for(ic) != "order":
            return bom
        # 订单隔离：禁止把 A 订单的坐标/Gerber 改绑到同机型 B 订单
        row_pn = (getattr(row, "purchase_no", None) or "").strip()
        if not row_pn:
            return None
        if (bom.purchase_no or "").strip() == row_pn:
            return bom
        matched = (
            db.query(BomModel)
            .filter(
                BomModel.internal_code == ic,
                BomModel.purchase_no == row_pn,
                BomModel.is_active.is_(True),
                BomModel.model_code == bom.model_code,
            )
            .order_by(BomModel.updated_at.desc(), BomModel.id.desc())
            .first()
        )
        return matched

    for customer in get_engineering_customers():
        ic = (customer.get("internal_code") or "").strip().upper()

        for row in db.query(PcbGerberPackage).filter(PcbGerberPackage.internal_code == ic).all():
            bom = _resolve_bom(ic, row)
            if not bom:
                continue
            changed = False
            if row.bom_model_id != bom.id:
                row.bom_model_id = bom.id
                changed = True
            if row.model_code != bom.model_code:
                row.model_code = bom.model_code
                changed = True
            if changed:
                updated += 1

        for row in db.query(PcbPlacementFile).filter(PcbPlacementFile.internal_code == ic).all():
            bom = _resolve_bom(ic, row)
            if not bom:
                continue
            changed = False
            if row.bom_model_id != bom.id:
                row.bom_model_id = bom.id
                changed = True
            if row.model_code != bom.model_code:
                row.model_code = bom.model_code
                changed = True
            if changed:
                updated += 1

    return {"updated": updated, "share_accessible": False, "assets_share_sync_enabled": False}
