"""产线工序扫码卡控：AOI → 插件 → 后焊 → ICT → 三防。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from board_gate import (
    STATION_COATING,
    STATION_LABELS,
    STATION_PLUGIN,
    STATION_POST_SOLDER,
    VALID_STATIONS,
    check_aoi_pass,
    check_ict_effective_pass,
    existing_scan,
    has_station,
    is_enjiu_context,
    norm_barcode,
    resolve_customer_id,
)
from laser_service import find_laser_batch_for_barcode
from models import ProcessScanRecord, SrmOrder


def _payload(row: ProcessScanRecord, *, status: str, message: str) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "station": row.station,
        "station_label": STATION_LABELS.get(row.station, row.station),
        "barcode": row.barcode,
        "purchase_no": row.purchase_no,
        "model_code": row.model_code,
        "scanned_at": row.scanned_at.isoformat(sep=" ", timespec="seconds") if row.scanned_at else None,
        "operator": row.operator,
        "id": row.id,
    }


def scan_process(
    db: Session,
    *,
    station: str,
    barcode: str,
    operator: str = "",
    purchase_no: str = "",
) -> dict[str, Any]:
    station = (station or "").strip().lower()
    if station not in VALID_STATIONS:
        return {"status": "blocked", "message": f"未知工位：{station}", "barcode": barcode, "station": station}

    code = norm_barcode(barcode)
    if not code:
        return {"status": "blocked", "message": "条码不能为空", "barcode": "", "station": station}

    existing = existing_scan(db, code, station)
    if existing:
        return _payload(existing, status="already_scanned", message="已扫过")

    # —— 卡控 ——
    if station == STATION_PLUGIN:
        # 恩玖：人工贴码，第一工序即插件，不查 AOI
        if not is_enjiu_context(db, barcode=code, purchase_no=purchase_no):
            aoi = check_aoi_pass(db, code)
            if not aoi["ok"]:
                return {
                    "status": "blocked",
                    "message": aoi["message"],
                    "barcode": code,
                    "station": station,
                    "station_label": STATION_LABELS[station],
                    "aoi_result": aoi.get("aoi_result"),
                }

    elif station == STATION_POST_SOLDER:
        if not has_station(db, code, STATION_PLUGIN):
            return {
                "status": "blocked",
                "message": "未过插件工序",
                "barcode": code,
                "station": station,
                "station_label": STATION_LABELS[station],
            }

    elif station == STATION_COATING:
        # 后焊 + 有效 ICT PASS（无后焊的机台 PASS 不认）
        if not has_station(db, code, STATION_POST_SOLDER):
            return {
                "status": "blocked",
                "message": "未过后焊工序",
                "barcode": code,
                "station": station,
                "station_label": STATION_LABELS[station],
            }
        ict = check_ict_effective_pass(db, code)
        if not ict["ok"]:
            return {
                "status": "blocked",
                "message": ict["message"],
                "barcode": code,
                "station": station,
                "station_label": STATION_LABELS[station],
                "ict_result": ict.get("ict_result"),
            }

    batch = find_laser_batch_for_barcode(db, code)
    pn = (purchase_no or "").strip() or (batch.purchase_no if batch else None)
    cid = batch.customer_id if batch else None
    # 机型必须以贴码/镭雕登记为准；禁止用同 PO 任意一行料号兜底（一单多机型会串）
    model_code = batch.model_code if batch else None
    laser_batch_id = batch.id if batch else None

    if not cid:
        cid = resolve_customer_id(db, barcode=code, purchase_no=pn or "")
    if pn and not cid:
        order = db.query(SrmOrder).filter(SrmOrder.purchase_no == pn).first()
        if order:
            cid = (order.customer_id or "").strip() or None

    row = ProcessScanRecord(
        barcode=code,
        station=station,
        purchase_no=pn,
        customer_id=cid,
        laser_batch_id=laser_batch_id,
        model_code=model_code,
        operator=(operator or "").strip() or None,
        scanned_at=datetime.utcnow(),
    )
    db.add(row)
    db.flush()
    return _payload(row, status="ok", message=f"{STATION_LABELS[station]}扫码成功")


def rematch_process_scans_to_laser(db: Session, limit: int = 20000) -> dict[str, int]:
    """按条码重挂工序扫码的采购单/机型（纠正历史「同 PO 首行料号」误写）。"""
    rows = (
        db.query(ProcessScanRecord)
        .order_by(ProcessScanRecord.id.desc())
        .limit(limit)
        .all()
    )
    fixed = 0
    scanned = 0
    for row in rows:
        scanned += 1
        batch = find_laser_batch_for_barcode(db, row.barcode)
        if not batch:
            continue
        changed = False
        if row.purchase_no != batch.purchase_no:
            row.purchase_no = batch.purchase_no
            changed = True
        if row.customer_id != batch.customer_id:
            row.customer_id = batch.customer_id
            changed = True
        if row.laser_batch_id != batch.id:
            row.laser_batch_id = batch.id
            changed = True
        if batch.model_code and row.model_code != batch.model_code:
            row.model_code = batch.model_code
            changed = True
        if changed:
            fixed += 1
    if fixed:
        db.flush()
    return {"scanned": scanned, "fixed": fixed}


def counts_by_purchase(db: Session, purchase_nos: list[str]) -> dict[str, dict[str, int]]:
    """purchase_no -> {plugin, post_solder, coating}（整单合计，勿用于多机型行展示）。"""
    out: dict[str, dict[str, int]] = {}
    if not purchase_nos:
        return out
    rows = (
        db.query(ProcessScanRecord.purchase_no, ProcessScanRecord.station, func.count(ProcessScanRecord.id))
        .filter(ProcessScanRecord.purchase_no.in_(purchase_nos))
        .group_by(ProcessScanRecord.purchase_no, ProcessScanRecord.station)
        .all()
    )
    for pn, station, n in rows:
        key = (pn or "").strip()
        if not key:
            continue
        bucket = out.setdefault(key, {STATION_PLUGIN: 0, STATION_POST_SOLDER: 0, STATION_COATING: 0})
        if station in bucket:
            bucket[station] = int(n or 0)
    return out


def counts_by_purchase_model(
    db: Session, purchase_nos: list[str]
) -> dict[tuple[str, str], dict[str, int]]:
    """(purchase_no, model_norm) -> {plugin, post_solder, coating}"""
    from engineering_service import normalize_code

    out: dict[tuple[str, str], dict[str, int]] = {}
    if not purchase_nos:
        return out
    rows = (
        db.query(
            ProcessScanRecord.purchase_no,
            ProcessScanRecord.model_code,
            ProcessScanRecord.station,
            func.count(ProcessScanRecord.id),
        )
        .filter(ProcessScanRecord.purchase_no.in_(purchase_nos))
        .group_by(ProcessScanRecord.purchase_no, ProcessScanRecord.model_code, ProcessScanRecord.station)
        .all()
    )
    empty = {STATION_PLUGIN: 0, STATION_POST_SOLDER: 0, STATION_COATING: 0}
    for pn, model_code, station, n in rows:
        pk = (pn or "").strip()
        mk = normalize_code(model_code)
        if not pk or not mk:
            continue
        bucket = out.setdefault((pk, mk), dict(empty))
        if station in bucket:
            bucket[station] = int(n or 0)
    return out


def list_scans_for_purchase(
    db: Session,
    purchase_no: str,
    *,
    station: str = "",
    keyword: str = "",
    limit: int = 3000,
) -> dict[str, Any]:
    pn = (purchase_no or "").strip()
    q = db.query(ProcessScanRecord).filter(ProcessScanRecord.purchase_no == pn)
    st = (station or "").strip().lower()
    if st in VALID_STATIONS:
        q = q.filter(ProcessScanRecord.station == st)
    kw = (keyword or "").strip().upper()
    if kw:
        q = q.filter(ProcessScanRecord.barcode.like(f"%{kw}%"))
    total = q.count()
    rows = q.order_by(ProcessScanRecord.scanned_at.desc(), ProcessScanRecord.id.desc()).limit(limit).all()
    return {
        "purchase_no": pn,
        "station": st,
        "total": total,
        "items": [
            {
                "id": r.id,
                "barcode": r.barcode,
                "station": r.station,
                "station_label": STATION_LABELS.get(r.station, r.station),
                "model_code": r.model_code,
                "operator": r.operator,
                "scanned_at": r.scanned_at.isoformat(sep=" ", timespec="seconds") if r.scanned_at else None,
            }
            for r in rows
        ],
    }
