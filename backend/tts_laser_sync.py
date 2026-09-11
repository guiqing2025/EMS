"""从菲利斯 TTS 同步镭雕/补码流水段到 EMS LaserBatch，并重挂 AOI。"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from laser_service import rematch_aoi_to_laser
from models import LaserBatch
from pcba_barcode import split_model_code
from tts_client import TtsClient, tts_cfg

logger = logging.getLogger(__name__)

def parse_qr_overview(qr: str) -> Optional[dict[str, Any]]:
    """解析 TTS 二维码流水范围。

    标准：D02002350926071180001-85000（D0 + 6位数字机型）
    字母机型：DS5000170226071000001-00010（D + S500017…，无中间的 0）
    个别异常位数（如流水 6 位）返回 None，由 skipped 统计。
    """
    text = (qr or "").strip().upper()
    if "-" not in text or not text.startswith("D"):
        return None
    left, right = text.split("-", 1)
    right = right.strip()
    if not re.fullmatch(r"\d{5}", right):
        return None
    # 去掉前缀 D0 或 D
    if left.startswith("D0") and len(left) > 2 and left[2].isdigit():
        body = left[2:]
    else:
        body = left[1:]  # D + mid(字母开头等)
    # 末尾：ver(2) + date(6) + seq_from(5) = 13
    if len(body) < 13 + 6:  # mid 至少 6
        return None
    seq_from_s = body[-5:]
    laser_date = body[-11:-5]
    ver = body[-13:-11]
    mid = body[:-13]
    if not re.fullmatch(r"[0-9A-Z]{6,8}", mid):
        return None
    if not re.fullmatch(r"\d{2}", ver) or not re.fullmatch(r"\d{6}", laser_date):
        return None
    if not re.fullmatch(r"\d{5}", seq_from_s):
        return None
    a, b = int(seq_from_s), int(right)
    seq_from, seq_to = (a, b) if a <= b else (b, a)
    mid_key = mid[-6:] if len(mid) > 6 else mid
    return {
        "model_mid": mid_key,
        "model_ver": ver.zfill(2),
        "laser_date": laser_date,
        "seq_from": seq_from,
        "seq_to": seq_to,
        "qr": text,
    }


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def history_to_batch_payload(row: dict, *, customer_id: str, customer_name: str) -> Optional[dict]:
    """TTS 流水登记 → LaserBatch 字段。"""
    purchase_no = (row.get("outsourcOrder") or row.get("outsourceOrder") or "").strip()
    model_code = (row.get("semiProductNo") or "").strip()
    qr = (row.get("qrCodeOverview") or "").strip()
    if not purchase_no or not qr:
        return None
    parsed = parse_qr_overview(qr)
    if not parsed:
        return None

    # 机型优先用 TTS 料号；解析失败则用条码中段
    mid = parsed["model_mid"]
    ver = parsed["model_ver"]
    model = model_code or f"120-{mid}-{ver}"
    if model_code:
        try:
            _prefix, mid, ver = split_model_code(model_code)
            model = model_code
        except ValueError:
            pass

    remark_parts = []
    responsible = (row.get("responsible") or "").strip()
    remark = (row.get("remark") or "").strip()
    process_num = (row.get("processNum") or "").strip()
    if responsible:
        remark_parts.append(f"负责人:{responsible}")
    if process_num:
        remark_parts.append(f"实产:{process_num}")
    if remark:
        remark_parts.append(remark)
    # 小批量多为补码
    qty_session = _to_float(process_num, 0)
    if qty_session and qty_session <= 200 and (remark or qty_session <= 50):
        if remark and any(k in remark for k in ("补", "纸质", "损耗", "清尾", "重工")):
            remark_parts.insert(0, "手工补码")
        elif qty_session <= 50:
            remark_parts.insert(0, "手工补码")

    order_qty = _to_float(row.get("batchNumber"), 0) or qty_session
    return {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "laser_date": parsed["laser_date"],
        "model_code": model,
        "model_mid": mid,
        "model_ver": ver,
        "purchase_no": purchase_no,
        "order_qty": order_qty,
        "seq_from": parsed["seq_from"],
        "seq_to": parsed["seq_to"],
        "remark": " · ".join(remark_parts) if remark_parts else None,
        "source": "tts",
        "tts_id": row.get("id"),
        "qr": parsed["qr"],
    }


def upsert_tts_batch(db: Session, payload: dict, *, created_by: str = "tts") -> tuple[LaserBatch, str]:
    """
    按 (客户, 日期, 机型中段, 版本, 流水起止) 匹配。
    TTS 为采购单归属的权威来源：若 Excel 旧数据挂错单号，直接改正。
    """
    now = datetime.utcnow()
    existing = (
        db.query(LaserBatch)
        .filter(
            LaserBatch.customer_id == payload["customer_id"],
            LaserBatch.laser_date == payload["laser_date"],
            LaserBatch.model_mid == payload["model_mid"],
            LaserBatch.model_ver == payload["model_ver"],
            LaserBatch.seq_from == payload["seq_from"],
            LaserBatch.seq_to == payload["seq_to"],
        )
        .order_by(LaserBatch.id.desc())
        .first()
    )
    if existing:
        changed = False
        action = "unchanged"
        if existing.purchase_no != payload["purchase_no"]:
            existing.purchase_no = payload["purchase_no"]
            changed = True
            action = "po_fixed"
        if float(existing.order_qty or 0) != float(payload["order_qty"] or 0):
            existing.order_qty = payload["order_qty"]
            changed = True
            if action == "unchanged":
                action = "updated"
        if (existing.remark or "") != (payload.get("remark") or ""):
            existing.remark = payload.get("remark")
            changed = True
            if action == "unchanged":
                action = "updated"
        if existing.model_code != payload["model_code"]:
            existing.model_code = payload["model_code"]
            changed = True
            if action == "unchanged":
                action = "updated"
        if existing.source != "tts":
            existing.source = "tts"
            changed = True
            if action == "unchanged":
                action = "updated"
        if changed:
            existing.updated_at = now
            existing.created_by = existing.created_by or created_by
        return existing, action

    row = LaserBatch(
        customer_id=payload["customer_id"],
        customer_name=payload.get("customer_name"),
        laser_date=payload["laser_date"],
        model_code=payload["model_code"],
        model_mid=payload["model_mid"],
        model_ver=payload["model_ver"],
        purchase_no=payload["purchase_no"],
        order_qty=payload["order_qty"],
        seq_from=payload["seq_from"],
        seq_to=payload["seq_to"],
        remark=payload.get("remark"),
        source="tts",
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    return row, "created"


def sync_laser_from_tts(
    db: Session,
    *,
    rematch: bool = True,
    created_by: str = "tts",
) -> dict[str, Any]:
    cfg = tts_cfg()
    client = TtsClient(cfg)
    client.login()
    histories = client.iter_all_histories()

    created = updated = po_fixed = unchanged = skipped = 0
    skip_samples: list[str] = []
    po_fix_samples: list[dict] = []

    for h in histories:
        payload = history_to_batch_payload(
            h,
            customer_id=cfg.get("customer_id") or "feilisi",
            customer_name=cfg.get("customer_name") or "客户A",
        )
        if not payload:
            skipped += 1
            if len(skip_samples) < 8:
                skip_samples.append(str(h.get("qrCodeOverview") or h.get("outsourcOrder") or ""))
            continue
        _row, action = upsert_tts_batch(db, payload, created_by=created_by)
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "po_fixed":
            po_fixed += 1
            if len(po_fix_samples) < 10:
                po_fix_samples.append(
                    {
                        "model": payload["model_code"],
                        "laser_date": payload["laser_date"],
                        "seq": f"{payload['seq_from']}-{payload['seq_to']}",
                        "purchase_no": payload["purchase_no"],
                        "qr": payload.get("qr"),
                    }
                )
        else:
            unchanged += 1

    db.flush()
    rematch_result = None
    if rematch:
        rematch_result = rematch_aoi_to_laser(db)

    return {
        "ok": True,
        "orders_histories": len(histories),
        "created": created,
        "updated": updated,
        "po_fixed": po_fixed,
        "unchanged": unchanged,
        "skipped": skipped,
        "skip_samples": skip_samples,
        "po_fix_samples": po_fix_samples,
        "rematch": rematch_result,
    }
