"""产线工序扫码卡控：按机型工序对照（SMT-AOI / 插件 / 后焊 / ICT / 三防）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from board_gate import (
    STATION_COATING,
    STATION_LABELS,
    STATION_PLUGIN,
    STATION_POST_SOLDER,
    VALID_STATIONS,
    check_aoi_pass,
    check_ict_effective_pass,
    check_pre_oven_aoi_pass,
    existing_scan,
    has_station,
    is_enjiu_context,
    norm_barcode,
    resolve_customer_id,
)
from laser_service import find_laser_batch_for_barcode
from models import ProcessScanRecord, SrmOrder
from pcba_barcode import is_enjiu_barcode, parse_pcba_barcode
from process_route_service import resolve_scan_gate_steps


def _normalize_process_barcode(raw: str) -> str:
    """规范工序条码；恩玖常见缺前导 0 的 15 位残码自动补全。"""
    code = norm_barcode(raw)
    if code.isdigit() and len(code) == 15:
        padded = "0" + code
        if is_enjiu_barcode(padded):
            return padded
    return code


def _is_plausible_process_barcode(code: str, *, enjiu_ctx: bool) -> bool:
    """拒绝扫枪截断残码（如 063、26310010），避免同一块板被记成多条。"""
    from barcode_quality import is_plausible_aoi_barcode

    t = (code or "").strip()
    if not t:
        return False
    if is_enjiu_barcode(t):
        return True
    if parse_pcba_barcode(t):
        return True
    if enjiu_ctx or t.isdigit():
        # 恩玖工单/纯数字：必须完整 16 位
        return False
    # 与 SMT/AOI 同一套形态规则（含拒绝缺前缀的亿兰科残码）
    return is_plausible_aoi_barcode(t)


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


def _unique_order_model(db: Session, purchase_no: str) -> str | None:
    """采购单仅一行机型时返回该料号；多机型返回 None（避免串单）。"""
    pn = (purchase_no or "").strip()
    if not pn:
        return None
    rows = (
        db.query(SrmOrder.product_goods_no)
        .filter(SrmOrder.purchase_no == pn)
        .distinct()
        .all()
    )
    codes = sorted({(r[0] or "").strip() for r in rows if (r[0] or "").strip()})
    if len(codes) == 1:
        return codes[0]
    return None


def _infer_model_on_purchase(db: Session, purchase_no: str, barcode: str) -> str | None:
    """条码在该 PO 订单行中唯一命中时返回料号（回补/兜底）。

    支持：恩玖物料段解析、亿兰科 YLK-xxxxA 贴码推断。
    """
    from pcba_barcode import parse_enjiu_barcode
    from smt_scan_service import _guess_model_from_barcode

    pn = (purchase_no or "").strip()
    if not pn:
        return None
    rows = (
        db.query(SrmOrder.product_goods_no)
        .filter(SrmOrder.purchase_no == pn)
        .distinct()
        .all()
    )
    goods_list = [(r[0] or "").strip() for r in rows if (r[0] or "").strip()]
    if not goods_list:
        return None

    def _match_goods(candidate: str) -> list[str]:
        cu = (candidate or "").strip().upper()
        if not cu:
            return []
        hits = []
        for g in goods_list:
            gu = g.upper()
            suffix = cu.split("-")[-1] if "-" in cu else cu
            if gu == cu or gu.endswith(suffix) or cu in gu.replace("-", ""):
                hits.append(g)
        return sorted(set(hits))

    parsed = parse_enjiu_barcode(barcode)
    material = (parsed.get("material_no") if parsed else "") or ""
    material = material.strip()
    if material:
        hits = _match_goods(material)
        if len(hits) == 1:
            return hits[0]

    guessed = _guess_model_from_barcode(barcode)
    if guessed:
        hits = _match_goods(guessed)
        if len(hits) == 1:
            return hits[0]
        if hits:
            # 多命中极少见；优先精确全等
            for g in hits:
                if g.upper() == guessed.upper():
                    return g
            return hits[0]
        # 条码明确含机型后缀且 PO 上应有对应行时，仍写入推断值便于列表归集
        return guessed
    return None



def _resolve_model_for_gate(
    db: Session,
    *,
    code: str,
    purchase_no: str,
    model_code: str,
    batch,
    prior_pn: str | None,
) -> tuple[str | None, str | None, str | None]:
    """返回 (model_code, purchase_no_hint, customer_id) 供工序对照卡控。"""
    selected_pn = (purchase_no or "").strip() or None
    laser_pn = (batch.purchase_no if batch else None) or None
    pn = prior_pn or laser_pn or selected_pn
    hint = (model_code or "").strip() or None
    resolved = hint
    if not resolved and pn:
        resolved = _unique_order_model(db, pn)
    if not resolved and pn:
        resolved = _infer_model_on_purchase(db, pn, code)
    if not resolved and batch and (batch.model_code or "").strip():
        resolved = (batch.model_code or "").strip()
    cid = None
    if batch and (batch.customer_id or "").strip():
        cid = (batch.customer_id or "").strip()
    if not cid and pn:
        order = db.query(SrmOrder.customer_id).filter(SrmOrder.purchase_no == pn).first()
        if order and order[0]:
            cid = str(order[0]).strip()
    if not cid:
        cid = resolve_customer_id(db, barcode=code, purchase_no=pn or "")
    return resolved, pn, cid


def scan_process(
    db: Session,
    *,
    station: str,
    barcode: str,
    operator: str = "",
    purchase_no: str = "",
    model_code: str = "",
) -> dict[str, Any]:
    station = (station or "").strip().lower()
    if station not in VALID_STATIONS:
        return {"status": "blocked", "message": f"未知工位：{station}", "barcode": barcode, "station": station}

    code = _normalize_process_barcode(barcode)
    if not code:
        return {"status": "blocked", "message": "条码不能为空", "barcode": "", "station": station}

    enjiu_ctx = is_enjiu_context(db, barcode=code, purchase_no=purchase_no)
    if not _is_plausible_process_barcode(code, enjiu_ctx=enjiu_ctx):
        return {
            "status": "blocked",
            "message": "条码过短或不完整，请重新扫描完整条码",
            "barcode": code,
            "station": station,
            "station_label": STATION_LABELS.get(station, station),
        }

    # 机型/订单硬卡必须先于「已扫过」：错机型再扫时要提示串机型，而不是已扫过
    batch = find_laser_batch_for_barcode(db, code)
    selected_pn = (purchase_no or "").strip() or None
    laser_pn = (batch.purchase_no if batch else None) or None

    # 已有上游工序挂单时：禁止扫到别的订单（同料号多 PO 时易串单）
    prior = (
        db.query(ProcessScanRecord)
        .filter(
            ProcessScanRecord.barcode == code,
            ProcessScanRecord.station.in_([STATION_PLUGIN, STATION_POST_SOLDER, STATION_COATING]),
            ProcessScanRecord.purchase_no.isnot(None),
            ProcessScanRecord.purchase_no != "",
        )
        .order_by(ProcessScanRecord.scanned_at.asc())
        .first()
    )
    prior_pn = (prior.purchase_no or "").strip() if prior else None
    if selected_pn and prior_pn and selected_pn != prior_pn:
        return {
            "status": "blocked",
            "message": f"该板属于订单 {prior_pn}，当前选中 {selected_pn}，请切换到正确订单再扫",
            "barcode": code,
            "station": station,
            "station_label": STATION_LABELS.get(station, station),
            "purchase_no": prior_pn,
        }
    if selected_pn and laser_pn and selected_pn != laser_pn and not prior_pn:
        return {
            "status": "blocked",
            "message": f"该板镭雕登记为 {laser_pn}，当前选中 {selected_pn}，请切换到正确订单再扫",
            "barcode": code,
            "station": station,
            "station_label": STATION_LABELS.get(station, station),
            "purchase_no": laser_pn,
        }

    # 选中机型与条码/镭雕机型硬卡（菲利斯等条码可解析时；不影响无法判定的板）
    from engineering_service import normalize_code
    from scan_line_guard import selection_mismatch_message

    sel_model = (model_code or "").strip()
    model_mismatch = selection_mismatch_message(
        selected_purchase_no="",  # 订单号已在上方按镭雕/上游工序处理
        selected_model_code=sel_model,
        barcode=code,
        laser_batch=batch,
    )
    if model_mismatch:
        return {
            "status": "blocked",
            "message": model_mismatch,
            "barcode": code,
            "station": station,
            "station_label": STATION_LABELS.get(station, station),
            "purchase_no": laser_pn or selected_pn,
        }

    existing = existing_scan(db, code, station)
    if existing:
        # 条码/镭雕无法判定时，仍用历史扫码机型/订单兜底防串单
        ex_pn = (existing.purchase_no or "").strip()
        ex_model = (existing.model_code or "").strip()
        if selected_pn and ex_pn and selected_pn != ex_pn:
            return {
                "status": "blocked",
                "message": f"该板属于订单 {ex_pn}，当前选中 {selected_pn}，请切换到正确订单再扫",
                "barcode": code,
                "station": station,
                "station_label": STATION_LABELS.get(station, station),
                "purchase_no": ex_pn,
                "model_code": ex_model or None,
            }
        if sel_model and ex_model and normalize_code(sel_model) != normalize_code(ex_model):
            return {
                "status": "blocked",
                "message": (
                    f"此板机型为 {ex_model}，当前订单行为 {sel_model}，"
                    f"请切换到正确机型订单再扫"
                ),
                "barcode": code,
                "station": station,
                "station_label": STATION_LABELS.get(station, station),
                "purchase_no": ex_pn or selected_pn,
                "model_code": ex_model,
            }
        return _payload(existing, status="already_scanned", message="已扫过")

    gate_model, _, gate_cid = _resolve_model_for_gate(
        db,
        code=code,
        purchase_no=purchase_no,
        model_code=model_code,
        batch=batch,
        prior_pn=prior_pn,
    )
    gate = resolve_scan_gate_steps(
        db,
        model_code=gate_model or "",
        customer_id=gate_cid or "",
    )
    steps = gate.get("steps") or {}
    require_smt = bool(steps.get("smt"))
    require_ict = bool(steps.get("test"))
    require_pre_oven_aoi = bool(steps.get("pre_oven_aoi"))
    require_post_solder = bool(steps.get("post_solder")) or bool(steps.get("post_oven_label"))
    require_plugin = bool(steps.get("insert"))

    # —— 卡控（按工序对照；未配置=最严；所有客户统一）——
    if station == STATION_PLUGIN:
        if require_smt:
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
        if require_pre_oven_aoi:
            pre_oven = check_pre_oven_aoi_pass(db, code)
            if not pre_oven["ok"]:
                blocked: dict[str, Any] = {
                    "status": "blocked",
                    "message": pre_oven["message"],
                    "barcode": code,
                    "station": station,
                    "station_label": STATION_LABELS[station],
                    "pre_oven_aoi_result": pre_oven.get("pre_oven_aoi_result"),
                }
                if pre_oven.get("pre_oven_confirm_required"):
                    blocked["pre_oven_confirm_required"] = True
                    blocked["pre_oven_fail_reason"] = pre_oven.get("pre_oven_fail_reason") or ""
                    blocked["pre_oven_fail_items"] = pre_oven.get("pre_oven_fail_items") or []
                return blocked

    elif station == STATION_COATING:
        # 按工序对照卡前置：勾了后焊才卡后焊；未勾后焊但勾了插件则卡插件
        if require_post_solder:
            if not has_station(db, code, STATION_POST_SOLDER):
                return {
                    "status": "blocked",
                    "message": "未过后焊工序",
                    "barcode": code,
                    "station": station,
                    "station_label": STATION_LABELS[station],
                }
        elif require_plugin:
            if not has_station(db, code, STATION_PLUGIN):
                return {
                    "status": "blocked",
                    "message": "未过插件工序",
                    "barcode": code,
                    "station": station,
                    "station_label": STATION_LABELS[station],
                }
        if require_ict:
            ict = check_ict_effective_pass(db, code)
            if not ict["ok"] and ict.get("reason") == "no_ict":
                from ict_sync import try_sync_ict_for_barcode

                sync = try_sync_ict_for_barcode(db, code, timeout_sec=8.0)
                if sync.get("synced"):
                    db.flush()
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

    # 人工工序：优先跟上游/镭雕已挂单；无选中且无上游时才用选中行
    pn = prior_pn or laser_pn or selected_pn
    cid = batch.customer_id if batch else None
    laser_batch_id = batch.id if batch else None

    # 机型：选中行传入 > 单机型 PO 兜底 > 恩玖条码在该 PO 唯一匹配 > 镭雕机型
    hint = (model_code or "").strip() or None
    resolved_model = hint
    if not resolved_model and pn:
        resolved_model = _unique_order_model(db, pn)
    if not resolved_model and pn:
        resolved_model = _infer_model_on_purchase(db, pn, code)
    if not resolved_model and batch and (batch.model_code or "").strip():
        resolved_model = (batch.model_code or "").strip()

    if not cid:
        cid = resolve_customer_id(db, barcode=code, purchase_no=pn or "")
    if pn and not cid:
        order = db.query(SrmOrder).filter(SrmOrder.purchase_no == pn).first()
        if order:
            cid = (order.customer_id or "").strip() or None

    now = datetime.utcnow()
    op = (operator or "").strip() or None
    plugin_backfilled = False
    if (
        station == STATION_POST_SOLDER
        and bool(steps.get("post_oven_label"))
        and not has_station(db, code, STATION_PLUGIN)
    ):
        db.add(
            ProcessScanRecord(
                barcode=code,
                station=STATION_PLUGIN,
                purchase_no=pn,
                customer_id=cid,
                laser_batch_id=laser_batch_id,
                model_code=resolved_model,
                operator=op,
                scanned_at=now,
            )
        )
        db.flush()
        plugin_backfilled = True

    row = ProcessScanRecord(
        barcode=code,
        station=station,
        purchase_no=pn,
        customer_id=cid,
        laser_batch_id=laser_batch_id,
        model_code=resolved_model,
        operator=op,
        scanned_at=now,
    )
    db.add(row)
    db.flush()
    msg = f"{STATION_LABELS[station]}扫码成功"
    if plugin_backfilled:
        msg = "后焊扫码成功（已补记插件）"
    return _payload(row, status="ok", message=msg)


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


def backfill_process_scan_model_codes(
    db: Session, limit: int = 50000, *, rematch_laser: bool = True
) -> dict[str, int]:
    """补全缺机型的工序扫码：可选先贴码/镭雕，再「采购单仅一机型」，再 AOI/ICT 条码机型。"""
    from models import AoiBoardResult, IctBoardResult

    laser: dict[str, int] = {"scanned": 0, "fixed": 0}
    if rematch_laser:
        laser = rematch_process_scans_to_laser(db, limit=limit)
    rows = (
        db.query(ProcessScanRecord)
        .filter(
            ProcessScanRecord.purchase_no.isnot(None),
            ProcessScanRecord.purchase_no != "",
            or_(ProcessScanRecord.model_code.is_(None), ProcessScanRecord.model_code == ""),
        )
        .order_by(ProcessScanRecord.id.desc())
        .limit(limit)
        .all()
    )
    model_cache: dict[str, str | None] = {}
    filled = 0
    filled_from_board = 0
    scanned = 0
    skipped_multi = 0
    for row in rows:
        scanned += 1
        pn = (row.purchase_no or "").strip()
        if not pn:
            continue
        if pn not in model_cache:
            model_cache[pn] = _unique_order_model(db, pn)
        model = model_cache[pn]
        if not model:
            # 多机型 PO：恩玖条码唯一匹配 → AOI/ICT 条码机型
            code = (row.barcode or "").strip()
            if code:
                model = _infer_model_on_purchase(db, pn, code)
            if not model and code:
                aoi = (
                    db.query(AoiBoardResult.model_code)
                    .filter(AoiBoardResult.barcode == code)
                    .first()
                )
                if aoi and (aoi[0] or "").strip():
                    model = (aoi[0] or "").strip()
                else:
                    ict = (
                        db.query(IctBoardResult.model_code)
                        .filter(IctBoardResult.barcode == code)
                        .first()
                    )
                    if ict and (ict[0] or "").strip():
                        model = (ict[0] or "").strip()
            if not model:
                skipped_multi += 1
                continue
            filled_from_board += 1
        row.model_code = model
        filled += 1
    if filled:
        db.flush()
    return {
        "laser_scanned": int(laser.get("scanned") or 0),
        "laser_fixed": int(laser.get("fixed") or 0),
        "order_scanned": scanned,
        "order_filled": filled,
        "order_filled_from_board": filled_from_board,
        "order_skipped_multi_model": skipped_multi,
    }


def counts_by_purchase(db: Session, purchase_nos: list[str]) -> dict[str, dict[str, int]]:
    """purchase_no -> {plugin, post_solder, coating}（整单合计，勿用于多机型行展示）。

    仅真实扫码条数；不再用交货/收货虚加。
    """
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


def _delivery_qty_by_purchase_model(
    db: Session, purchase_nos: list[str]
) -> dict[tuple[str, str], int]:
    """(purchase_no, model_norm) -> max(交货, 收货)。保留供其它统计使用；列表工序/AOI/ICT 不再用此虚加。"""
    from engineering_service import normalize_code

    out: dict[tuple[str, str], int] = {}
    if not purchase_nos:
        return out
    rows = (
        db.query(
            SrmOrder.purchase_no,
            SrmOrder.product_goods_no,
            SrmOrder.delivery_qty,
            SrmOrder.receive_qty,
        )
        .filter(SrmOrder.purchase_no.in_(purchase_nos))
        .all()
    )
    for pn, model_code, delivery_qty, receive_qty in rows:
        pk = (pn or "").strip()
        mk = normalize_code(model_code)
        if not pk or not mk:
            continue
        try:
            deliv = int(float(delivery_qty or 0))
        except (TypeError, ValueError):
            deliv = 0
        try:
            recv = int(float(receive_qty or 0))
        except (TypeError, ValueError):
            recv = 0
        qty = max(deliv, recv)
        if qty <= 0:
            continue
        key = (pk, mk)
        out[key] = int(out.get(key, 0)) + qty
    return out


def counts_by_purchase_model(
    db: Session, purchase_nos: list[str]
) -> dict[tuple[str, str], dict[str, int]]:
    """(purchase_no, model_norm) -> {plugin, post_solder, coating}

    仅真实工序扫码条数；不再用交货/收货虚加。不影响扫码卡控与追溯。
    """
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
