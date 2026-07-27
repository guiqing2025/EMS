"""永联订单物料替代明细（图片发料单版式：一字对齐客户传图）。"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from models import BomLine, BomModel, SubstitutionRule, YonglianSubSheet, YonglianSubSheetLine
from substitution_service import normalize_code, reload_substitution_cache_from_db

logger = logging.getLogger(__name__)

_CODE_RE = re.compile(r"\d{2}\.\d{2,4}\.\d{4,}")
_PO_RE = re.compile(r"(?:订单号|委外订单号)[：:\s]*([0-9A-Za-z\-]+)", re.I)
_QTY_RE = re.compile(r"订单\s*(\d+)\s*PCS", re.I)
_MODEL_RE = re.compile(r"\b(91\.\d{4}\.\d+)\b")


def _s(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def sheet_to_dict(sheet: YonglianSubSheet, *, with_lines: bool = True) -> dict:
    payload = {
        "id": sheet.id,
        "customer_id": sheet.customer_id,
        "internal_code": sheet.internal_code or "A067",
        "model_code": sheet.model_code or "",
        "purchase_no": sheet.purchase_no or "",
        "order_qty": sheet.order_qty,
        "process": sheet.process or "SMT",
        "fixture_note": sheet.fixture_note or "",
        "source_type": sheet.source_type or "",
        "source_file": sheet.source_file or "",
        "line_count": sheet.line_count or 0,
        "synced_at": sheet.synced_at.isoformat() if sheet.synced_at else None,
        "created_at": sheet.created_at.isoformat() if sheet.created_at else None,
    }
    if with_lines:
        lines = sorted(sheet.lines or [], key=lambda x: (x.sort_order or 0, x.id or 0))
        payload["lines"] = [line_to_dict(ln) for ln in lines]
    return payload


def line_to_dict(ln: YonglianSubSheetLine) -> dict:
    return {
        "id": ln.id,
        "seq": ln.seq,
        "mount_type": ln.mount_type or "",
        "mount_side": ln.mount_side or "",
        "material_code": ln.material_code or "",
        "material_name": ln.material_name or "",
        "spec": ln.spec or "",
        "unit": ln.unit or "",
        "qty_per": ln.qty_per,
        "position": ln.position or "",
        "required_qty": ln.required_qty,
        "issue_qty": ln.issue_qty,
        "return_qty": ln.return_qty,
        "sort_order": ln.sort_order or 0,
    }


def list_sheets(db: Session, *, keyword: str = "") -> list[dict]:
    q = db.query(YonglianSubSheet).filter(YonglianSubSheet.customer_id == "yonglian")
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (YonglianSubSheet.purchase_no.ilike(like))
            | (YonglianSubSheet.model_code.ilike(like))
            | (YonglianSubSheet.fixture_note.ilike(like))
        )
    rows = q.order_by(YonglianSubSheet.id.desc()).all()
    return [sheet_to_dict(r, with_lines=False) for r in rows]


def get_sheet(db: Session, sheet_id: int) -> dict:
    row = db.query(YonglianSubSheet).filter(YonglianSubSheet.id == sheet_id).first()
    if not row:
        raise ValueError("替代明细单不存在")
    return sheet_to_dict(row, with_lines=True)


def delete_sheet(db: Session, sheet_id: int) -> None:
    row = db.query(YonglianSubSheet).filter(YonglianSubSheet.id == sheet_id).first()
    if not row:
        raise ValueError("替代明细单不存在")
    db.query(YonglianSubSheetLine).filter(YonglianSubSheetLine.sheet_id == sheet_id).delete(
        synchronize_session=False
    )
    db.delete(row)
    db.flush()


def upsert_sheet(
    db: Session,
    *,
    header: dict,
    lines: list[dict],
    source_type: str = "image",
    source_file: str = "",
    replace_rules: bool = True,
) -> dict:
    purchase_no = _s(header.get("purchase_no"))
    model_code = _s(header.get("model_code"))
    if not purchase_no:
        raise ValueError("缺少订单号")
    if not lines:
        raise ValueError("明细为空")

    now = datetime.utcnow()
    sheet = (
        db.query(YonglianSubSheet)
        .filter(
            YonglianSubSheet.customer_id == "yonglian",
            YonglianSubSheet.purchase_no == purchase_no,
        )
        .first()
    )
    if not sheet:
        sheet = YonglianSubSheet(customer_id="yonglian", purchase_no=purchase_no)
        db.add(sheet)
        db.flush()

    sheet.internal_code = _s(header.get("internal_code")) or "A067"
    sheet.model_code = model_code
    sheet.order_qty = float(header.get("order_qty") or 0) or None
    sheet.process = _s(header.get("process")) or "SMT"
    sheet.fixture_note = _s(header.get("fixture_note")) or None
    sheet.source_type = source_type
    sheet.source_file = source_file or None
    sheet.line_count = len(lines)
    sheet.synced_at = now
    sheet.updated_at = now

    db.query(YonglianSubSheetLine).filter(YonglianSubSheetLine.sheet_id == sheet.id).delete(
        synchronize_session=False
    )
    for i, raw in enumerate(lines, start=1):
        code = normalize_code(raw.get("material_code"))
        if not code:
            continue
        db.add(
            YonglianSubSheetLine(
                sheet_id=sheet.id,
                seq=int(raw.get("seq") or i),
                mount_type=_s(raw.get("mount_type")) or "SMT",
                mount_side=_s(raw.get("mount_side")) or "",
                material_code=code,
                material_name=_s(raw.get("material_name")) or None,
                spec=_s(raw.get("spec")) or None,
                unit=_s(raw.get("unit")) or "Pcs",
                qty_per=float(raw["qty_per"]) if raw.get("qty_per") not in (None, "") else None,
                position=_s(raw.get("position")) or None,
                required_qty=float(raw["required_qty"])
                if raw.get("required_qty") not in (None, "")
                else None,
                issue_qty=float(raw["issue_qty"]) if raw.get("issue_qty") not in (None, "") else None,
                return_qty=float(raw["return_qty"])
                if raw.get("return_qty") not in (None, "")
                else None,
                sort_order=i,
            )
        )
    db.flush()

    rules_msg = ""
    if replace_rules:
        rules_msg = _sync_rules_from_sheet(db, sheet)

    db.refresh(sheet)
    payload = sheet_to_dict(sheet, with_lines=True)
    payload["message"] = f"已保存订单 {purchase_no} · {len(lines)} 行" + (
        f"；{rules_msg}" if rules_msg else ""
    )
    return payload


def _sync_rules_from_sheet(db: Session, sheet: YonglianSubSheet) -> str:
    """
    用本单明细对照 BOM 同位置料号，生成永联替代规则（BOM 原料 → 发料品号）。
    先清空该客户旧规则，避免与发料单冲突。
    """
    deleted = (
        db.query(SubstitutionRule)
        .filter(SubstitutionRule.customer_id == "yonglian")
        .delete(synchronize_session=False)
    )
    bom = None
    if sheet.model_code and sheet.purchase_no:
        bom = (
            db.query(BomModel)
            .filter(
                BomModel.internal_code == (sheet.internal_code or "A067"),
                BomModel.model_code == sheet.model_code,
                BomModel.purchase_no == sheet.purchase_no,
                BomModel.is_active.is_(True),
            )
            .first()
        )
    if not bom and sheet.model_code:
        bom = (
            db.query(BomModel)
            .filter(
                BomModel.internal_code == (sheet.internal_code or "A067"),
                BomModel.model_code == sheet.model_code,
                BomModel.is_active.is_(True),
            )
            .order_by(BomModel.id.desc())
            .first()
        )

    inserted = 0
    batch = uuid.uuid4().hex[:16]
    now = datetime.utcnow()
    if bom:
        bom_lines = (
            db.query(BomLine)
            .filter(BomLine.bom_model_id == bom.id, BomLine.is_active.is_(True))
            .all()
        )
        # 位号 → BOM 料号
        pos_to_bom: dict[str, str] = {}
        for bl in bom_lines:
            for token in re.split(r"[,，\s]+", bl.position or ""):
                t = token.strip().upper()
                if t:
                    pos_to_bom[t] = normalize_code(bl.material_code)

        seen: set[tuple[str, str]] = set()
        for ln in sheet.lines or []:
            issue = normalize_code(ln.material_code)
            if not issue:
                continue
            for token in re.split(r"[,，\s]+", ln.position or ""):
                t = token.strip().upper()
                bom_code = pos_to_bom.get(t)
                if not bom_code or bom_code == issue:
                    continue
                key = (bom_code, issue)
                if key in seen:
                    continue
                seen.add(key)
                db.add(
                    SubstitutionRule(
                        customer_id="yonglian",
                        comp_code=bom_code,
                        comp_name=None,
                        sub_code=issue,
                        sub_name=ln.material_name,
                        sub_spec=ln.spec,
                        sub_unit=ln.unit,
                        relation_type="替代料件",
                        remark=f"订单 {sheet.purchase_no} · 位号 {t}",
                        source_type="yonglian_sheet",
                        source_file=sheet.source_file,
                        import_batch_id=batch,
                        synced_at=now,
                    )
                )
                inserted += 1

    reload_substitution_cache_from_db(db, "yonglian")
    return f"对照 BOM 写入替代规则 {inserted} 条（清空旧规则 {deleted}）"


def parse_yonglian_sheet_image(content: bytes) -> dict:
    """OCR 永联发料/替代明细图，尽量还原表头与行。"""
    from substitution_import import _ocr_image_bytes

    text = _ocr_image_bytes(content)
    header = {
        "internal_code": "A067",
        "model_code": "",
        "purchase_no": "",
        "order_qty": None,
        "process": "SMT",
        "fixture_note": "",
    }
    if "A067" in text or "客户" in text:
        header["internal_code"] = "A067"
    m = _PO_RE.search(text)
    if m:
        header["purchase_no"] = m.group(1).strip()
    m = _QTY_RE.search(text.replace(" ", ""))
    if not m:
        m = re.search(r"订单\s*(\d+)\s*PCS", text, re.I)
    if m:
        header["order_qty"] = float(m.group(1))
    m = _MODEL_RE.search(text.replace(" ", ""))
    if m:
        header["model_code"] = m.group(1)
    else:
        # OCR 常把点号拆开：91. 0302. 100276
        m2 = re.search(r"91\s*\.\s*0302\s*\.\s*(\d+)", text)
        if m2:
            header["model_code"] = f"91.0302.{m2.group(1)}"
    if "钢网治具客供" in text.replace(" ", ""):
        header["fixture_note"] = "钢网治具客供"
    if re.search(r"\bDIP\b", text):
        header["process"] = "DIP"
    elif re.search(r"\bSMT\b", text):
        header["process"] = "SMT"

    # 压缩 OCR 空格后的料号
    compact = re.sub(r"(\d)\s+\.\s+(\d)", r"\1.\2", text)
    compact = re.sub(r"(\d)\s+(\d{4})\s+(\d)", r"\1.\2.\3", compact)

    lines: list[dict] = []
    # 按「SMT」行块粗切
    blocks = re.split(r"(?=\b\d{1,3}\s*\n?\s*SMT\b)|(?=\bSMT\b)", compact)
    seq_guess = 0
    for block in blocks:
        b = block.strip()
        if "SMT" not in b and "DIP" not in b:
            continue
        codes = _CODE_RE.findall(b.replace(" ", ""))
        if not codes:
            # 再试去空格
            codes = _CODE_RE.findall(re.sub(r"\s+", "", b))
        if not codes:
            continue
        code = codes[0]
        seq_guess += 1
        side = "T面" if "T面" in b or "T 面" in b else ("B面" if "B面" in b else "T面")
        # 用量：单独数字行启发式
        qty_per = None
        req = None
        nums = re.findall(r"(?m)^\s*(\d+)\s*$", b)
        if len(nums) >= 2:
            qty_per = float(nums[-2])
            req = float(nums[-1])
        elif len(nums) == 1:
            req = float(nums[0])
        # 位号
        pos_m = re.findall(r"\b([A-Z]{1,3}\d{1,4}(?:\s*,\s*[A-Z]{1,3}\d{1,4})*)\b", b)
        position = ""
        for cand in pos_m:
            if cand.upper() in ("SMT", "DIP", "PCS", "NP0", "X7R", "X5R", "ROHS"):
                continue
            if re.match(r"^[A-Z]{1,3}\d+", cand):
                position = cand.replace(" ", "")
                break
        lines.append(
            {
                "seq": seq_guess,
                "mount_type": "SMT" if "SMT" in b else "DIP",
                "mount_side": side,
                "material_code": code,
                "material_name": "",
                "spec": "",
                "unit": "Pcs",
                "qty_per": qty_per,
                "position": position,
                "required_qty": req,
            }
        )

    return {
        "header": header,
        "lines": lines,
        "raw_text": text[:6000],
        "message": f"OCR 识别到表头订单 {header.get('purchase_no') or '—'}，明细候选 {len(lines)} 行（请核对后确认）",
        "format": "yonglian_sheet_image",
    }


# 本图「一字不差」录入（01-202607-CG-0320 / 91.0302.100276）
SHEET_202607_CG_0320 = {
    "header": {
        "internal_code": "A067",
        "model_code": "91.0302.100276",
        "purchase_no": "01-202607-CG-0320",
        "order_qty": 20,
        "process": "SMT",
        "fixture_note": "钢网治具客供",
    },
    "lines": [
        {"seq": 1, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0709.021500", "material_name": "片状电阻器", "spec": "片状电阻器-1/4W-51Ω±5%-1206-", "unit": "Pcs", "qty_per": 1, "position": "R245", "required_qty": 20},
        {"seq": 2, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0709.033700", "material_name": "片状电阻器", "spec": "片状电阻器-1/4W-27Ω±1%-1206-", "unit": "Pcs", "qty_per": 1, "position": "R998", "required_qty": 20},
        {"seq": 3, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0709.058100", "material_name": "片状电阻器", "spec": "片状电阻器-1/8W-330Ω±1%-0805-", "unit": "Pcs", "qty_per": 1, "position": "R89", "required_qty": 20},
        {"seq": 4, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0709.075802", "material_name": "片状电阻器", "spec": "片状厚膜电阻器-1/10W-15KΩ±1%-0603-", "unit": "Pcs", "qty_per": 1, "position": "R3", "required_qty": 20},
        {"seq": 5, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0709.094400", "material_name": "片状电阻器", "spec": "片状厚膜电阻器-1/10W-4.32KΩ±1%-0603-", "unit": "Pcs", "qty_per": 1, "position": "R262", "required_qty": 20},
        {"seq": 6, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0807.041400", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-50V-560PF±5%-NP0-0603-0.9mm-", "unit": "Pcs", "qty_per": 1, "position": "C603", "required_qty": 20},
        {"seq": 7, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0807.060400", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-25V-4.7uF±10%-X7R-1206-1.8mm-", "unit": "Pcs", "qty_per": 1, "position": "C336", "required_qty": 20},
        {"seq": 8, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0807.070000", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-200V-220pF-±5%-NP0-0805-1.27mm-350.00-", "unit": "Pcs", "qty_per": 1, "position": "C325", "required_qty": 20},
        {"seq": 9, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.0807.078900", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-50V-5.6nF±10%-X7R-0603-", "unit": "Pcs", "qty_per": 2, "position": "C605,C600", "required_qty": 40},
        {"seq": 10, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.1501.021502", "material_name": "肖特基二极管", "spec": "肖特基二极管-40V-200mA-共阳-SOT-23-", "unit": "Pcs", "qty_per": 1, "position": "D31", "required_qty": 20},
        {"seq": 11, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.1504.000103", "material_name": "稳压二极管", "spec": "稳压二极管/5.1V/0.225W/SOT-23-", "unit": "Pcs", "qty_per": 1, "position": "D23", "required_qty": 20},
        {"seq": 12, "mount_type": "SMT", "mount_side": "T面", "material_code": "90.1506.004202", "material_name": "绝缘栅场效应管", "spec": "绝缘栅场效应管-N沟道-200V-9A-0.4Ω-±20V-TO-252-AA", "unit": "Pcs", "qty_per": 1, "position": "Q62", "required_qty": 20},
        {"seq": 13, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0709.000300", "material_name": "片状电阻器", "spec": "片状电阻器1/10W-4.7kΩ-±1%-0603", "unit": "Pcs", "qty_per": 1, "position": "R266", "required_qty": 20},
        {"seq": 14, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0709.006800", "material_name": "片状电阻器", "spec": "片状电阻器1/10W-56KΩ±1%-0603-", "unit": "Pcs", "qty_per": 2, "position": "R12,R21", "required_qty": 40},
        {"seq": 15, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0709.009600", "material_name": "片状电阻器", "spec": "片状电阻器-1/3W-150KΩ±1%-1210-", "unit": "Pcs", "qty_per": 1, "position": "R659", "required_qty": 20},
        {"seq": 16, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0709.009700", "material_name": "片状电阻器", "spec": "片状电阻器1/10W-2.4kΩ±1%-0603", "unit": "Pcs", "qty_per": 1, "position": "R609", "required_qty": 20},
        {"seq": 17, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0709.020900", "material_name": "片状电阻器", "spec": "片状电阻器-1/10W-1.8kΩ±1%-0603-", "unit": "Pcs", "qty_per": 1, "position": "R1025", "required_qty": 20},
        {"seq": 18, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0709.100244", "material_name": "片状电阻", "spec": "片状厚膜电阻-1/4W-3.3kΩ-±1%-1206-RoHS", "unit": "Pcs", "qty_per": 1, "position": "R605", "required_qty": 20},
        {"seq": 19, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0709.100340", "material_name": "片状电阻器", "spec": "片状电阻器_1/2W_43KΩ_1%_1210", "unit": "Pcs", "qty_per": 1, "position": "R660", "required_qty": 20},
        {"seq": 20, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0807.000200", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-50V-10nF±10%-X7R-0603-0.9mm-", "unit": "Pcs", "qty_per": 1, "position": "C23", "required_qty": 20},
        {"seq": 21, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0807.000300", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-16V-0.47μF±10%-X7R-0603-0.9mm-", "unit": "Pcs", "qty_per": 1, "position": "C604", "required_qty": 20},
        {"seq": 22, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0807.001701", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-25V-10uF-±10%-X7R-1206-1.60mm-", "unit": "Pcs", "qty_per": 2, "position": "C2,C3", "required_qty": 40},
        {"seq": 23, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0807.001800", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-10V-22μF±10%-X7R-1206-1.60mm-", "unit": "Pcs", "qty_per": 1, "position": "C322", "required_qty": 20},
        {"seq": 24, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0807.003700", "material_name": "片状陶瓷电容器", "spec": "片状陶瓷电容器-25V-22uF±10%-X5R-1206-", "unit": "Pcs", "qty_per": 3, "position": "C4,C5,C20", "required_qty": 60},
        {"seq": 25, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0807.008400", "material_name": "片状电容器", "spec": "片状陶瓷电容器-50V-10pF-±5%-NP0-0603", "unit": "Pcs", "qty_per": 1, "position": "C22", "required_qty": 20},
        {"seq": 26, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.0807.100169", "material_name": "片状电容", "spec": "片状陶瓷电容-50V-10pF-±5%-0603-NP0-RoHS", "unit": "Pcs", "qty_per": 1, "position": "C822", "required_qty": 20},
        {"seq": 27, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.1003.100021", "material_name": "贴片电感", "spec": "贴片电感_HGYT0530B-100M_10uH_-_-_5.8*5*3mm_", "unit": "Pcs", "qty_per": 1, "position": "L1", "required_qty": 20},
        {"seq": 28, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.1501.100084", "material_name": "快恢复二极管", "spec": "快恢复二极管_200V_5A_0.95V_35ns_SMCG", "unit": "Pcs", "qty_per": 1, "position": "D200", "required_qty": 20},
        {"seq": 29, "mount_type": "SMT", "mount_side": "T面", "material_code": "91.1501.100104", "material_name": "碳化硅肖特基二极管", "spec": "碳化硅肖特基二极管_1200V_2A_1.3V / SMB-C", "unit": "Pcs", "qty_per": 2, "position": "D171,D172", "required_qty": 40},
    ],
}


def seed_sheet_from_image_0320(db: Session, *, source_file: str = "") -> dict:
    data = SHEET_202607_CG_0320
    return upsert_sheet(
        db,
        header=data["header"],
        lines=data["lines"],
        source_type="image",
        source_file=source_file or "永联替代明细图-01-202607-CG-0320",
        replace_rules=True,
    )
