import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import quote

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from barcode_quality import purge_truncated_suffixes, validate_packing_barcode
from board_gate import check_packing_gate
from laser_service import resolve_packing_line_by_laser
from models import OrderScan, Shipment, ShipmentBox, ShipmentSlip, SrmOrder

SCAN_LOG_DIR = Path(__file__).parent / "data" / "scans"
SCAN_STATUS_PENDING = "pending"
SCAN_STATUS_AWAITING = "awaiting_approve"  # 已点发货、待 dxgc/dxgc002/WGQ 确认
SCAN_STATUS_SHIPPED = "shipped"

BOX_STATUS_OPEN = "open"
BOX_STATUS_SEALED = "sealed"
BOX_STATUS_AWAITING = "awaiting"
BOX_STATUS_SHIPPED = "shipped"

SHIP_APPROVAL_PENDING = "pending"
SHIP_APPROVAL_APPROVED = "approved"

# 历史发货补录：合成条码前缀（不走 register_scan；勿用 legacy: 否则 get_scan_stats 不计）
BACKFILL_BARCODE_PREFIX = "__EMS_BF__"
BACKFILL_OPERATOR_PREFIX = "backfill:"
BACKFILL_REMARK_TAG = "【历史发货补录】"

COMPANY_NAME = "深圳鼎雄电子科技有限公司"


def expand_box_qtys(total: int, boxes: int, per: int) -> list[int]:
    """按箱数×每箱展开本箱数量；最后一箱可少于每箱（尾数）。"""
    try:
        total_n = int(total or 0)
        boxes_n = int(boxes or 1)
        per_n = int(per or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("箱数 / 每箱数量无效") from exc
    if total_n <= 0:
        raise ValueError("发货数量须大于 0")
    if boxes_n < 1:
        raise ValueError("箱数须大于 0")
    if per_n < 1:
        raise ValueError("每箱数量须大于 0")
    if boxes_n * per_n < total_n:
        raise ValueError(
            f"箱数×每箱数量 {boxes_n}×{per_n}={boxes_n * per_n} 小于发货数 {total_n}"
        )
    if boxes_n > 1 and (boxes_n - 1) * per_n >= total_n:
        raise ValueError(
            f"箱数偏多：前 {boxes_n - 1} 箱按每箱 {per_n} 已能装完 {total_n}，请减少箱数"
        )
    out: list[int] = []
    remain = total_n
    for i in range(boxes_n):
        left = boxes_n - i
        q = remain if left == 1 else min(per_n, remain)
        if q <= 0:
            raise ValueError("装箱数量无效")
        out.append(q)
        remain -= q
    if remain != 0:
        raise ValueError("装箱数量与发货数不一致")
    return out


def expand_pack_specs(specs: list, remainder: int = 0) -> list[int]:
    """多种棉规格展开为每箱数量；尾数单独一箱。不改扫码入库。"""
    out: list[int] = []
    rows = specs if isinstance(specs, list) else []
    for i, spec in enumerate(rows, start=1):
        if not isinstance(spec, dict):
            continue
        try:
            qty = int(spec.get("qty") or 0)
            per = int(spec.get("qty_per_box") or spec.get("per") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第{i}种棉数量无效") from exc
        if qty <= 0:
            continue
        if per < 1:
            raise ValueError(f"第{i}种棉请填写每箱数量")
        try:
            boxes = int(spec.get("box_count") or 0)
        except (TypeError, ValueError):
            boxes = 0
        if boxes < 1:
            boxes = (qty + per - 1) // per
        try:
            chunk = expand_box_qtys(qty, boxes, per)
        except ValueError as exc:
            raise ValueError(f"第{i}种棉：{exc}") from exc
        out.extend(chunk)
    try:
        rem = int(remainder or 0)
    except (TypeError, ValueError):
        rem = 0
    if rem < 0:
        raise ValueError("尾数不能为负数")
    if rem > 0:
        out.append(rem)
    if not out:
        raise ValueError("请至少填写一种棉的装箱数量")
    return out


def format_pack_note(specs: list, remainder: int = 0) -> str:
    parts: list[str] = []
    rows = specs if isinstance(specs, list) else []
    for spec in rows:
        if not isinstance(spec, dict):
            continue
        try:
            qty = int(spec.get("qty") or 0)
            per = int(spec.get("qty_per_box") or spec.get("per") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or per < 1:
            continue
        try:
            boxes = int(spec.get("box_count") or 0)
        except (TypeError, ValueError):
            boxes = 0
        if boxes < 1:
            boxes = (qty + per - 1) // per
        parts.append(f"{qty}={per}/箱({boxes}箱)")
    try:
        rem = int(remainder or 0)
    except (TypeError, ValueError):
        rem = 0
    if rem > 0:
        parts.append(f"尾数1箱×{rem}")
    if not parts:
        return ""
    return "装箱：" + " + ".join(parts)


def format_pack_note_from_qtys(qtys: list[int]) -> str:
    """按实际每箱片数汇总，给审核人打标签看。"""
    vals = [int(x) for x in qtys if int(x or 0) > 0]
    if not vals:
        return ""
    total = sum(vals)
    grouped = Counter(vals)
    if len(grouped) == 1:
        per, n = next(iter(grouped.items()))
        return f"装箱：{total}={per}/箱({n}箱)"
    parts = [f"{per}/箱({n}箱)" for per, n in sorted(grouped.items(), key=lambda x: (-x[1], -x[0]))]
    return f"装箱：{total}=" + " + ".join(parts)


def _typical_qty_per_box(qtys: list[int]) -> int:
    vals = [int(x) for x in qtys if int(x or 0) > 0]
    if not vals:
        return 1
    return int(Counter(vals).most_common(1)[0][0])


def _public_base_url() -> str:
    return (os.environ.get("EMS_PUBLIC_URL") or "http://192.168.2.168:8888").rstrip("/")


def box_trace_url(box_no: str) -> str:
    no = quote((box_no or "").strip(), safe="")
    return f"{_public_base_url()}/static/box_trace.html?no={no}"


def _next_box_no(db: Session) -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"BX-{today}-"
    last = (
        db.query(ShipmentBox)
        .filter(ShipmentBox.box_no.like(f"{prefix}%"))
        .order_by(ShipmentBox.id.desc())
        .first()
    )
    seq = 1
    if last and last.box_no:
        try:
            seq = int(str(last.box_no).split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:06d}"


def _create_boxes_for_shipment(
    db: Session,
    shipment: Shipment,
    scans: list[OrderScan],
    box_qtys: Optional[list[int]] = None,
) -> list[ShipmentBox]:
    if box_qtys:
        try:
            qtys = [int(x) for x in box_qtys if int(x) > 0]
        except (TypeError, ValueError) as exc:
            raise ValueError("装箱数量无效") from exc
        if sum(qtys) != int(shipment.qty or 0):
            raise ValueError("装箱数量与发货数不一致")
    else:
        try:
            qtys = expand_box_qtys(
                int(shipment.qty or 0),
                int(shipment.box_count or 1),
                int(getattr(shipment, "qty_per_box", None) or 1),
            )
        except ValueError:
            qty = int(shipment.qty or 0)
            qtys = [qty] if qty > 0 else []
    if not qtys:
        return []
    boxes: list[ShipmentBox] = []
    offset = 0
    total_boxes = len(qtys)
    for idx, box_qty in enumerate(qtys, start=1):
        box = ShipmentBox(
            box_no=_next_box_no(db),
            shipment_id=shipment.id,
            slip_id=shipment.slip_id,
            line_key=shipment.line_key,
            purchase_no=shipment.purchase_no or "",
            product_goods_no=shipment.product_goods_no,
            product_goods_name=shipment.product_goods_name,
            customer_name=shipment.customer_name,
            box_index=idx,
            box_count=total_boxes,
            qty=int(box_qty),
            qty_target=int(box_qty),
            status=BOX_STATUS_SEALED,
            pack_mode="ship",
            ship_date=shipment.ship_date or "",
            created_at=datetime.utcnow(),
        )
        db.add(box)
        db.flush()
        chunk = scans[offset : offset + int(box_qty)]
        for scan in chunk:
            scan.box_id = box.id
        offset += int(box_qty)
        boxes.append(box)
    return boxes


def ensure_shipment_boxes(db: Session, shipment: Shipment) -> list[ShipmentBox]:
    existing = (
        db.query(ShipmentBox)
        .filter(ShipmentBox.shipment_id == shipment.id)
        .order_by(ShipmentBox.box_index.asc(), ShipmentBox.id.asc())
        .all()
    )
    if existing:
        return existing
    scans = (
        db.query(OrderScan)
        .filter(OrderScan.shipment_id == shipment.id)
        .order_by(OrderScan.id.asc())
        .all()
    )
    return _create_boxes_for_shipment(db, shipment, scans)


def _box_payload(db: Session, box: ShipmentBox, *, with_codes: bool = False) -> dict:
    filled = (
        db.query(func.count(OrderScan.id))
        .filter(OrderScan.box_id == box.id)
        .scalar()
        or 0
    )
    target = int(box.qty_target or box.qty or 0)
    data = {
        "id": box.id,
        "box_no": box.box_no,
        "line_key": box.line_key,
        "purchase_no": box.purchase_no or "",
        "goods_no": box.product_goods_no or "",
        "goods_name": box.product_goods_name or "",
        "customer_name": box.customer_name or "",
        "qty": int(filled),
        "qty_target": target,
        "status": box.status or BOX_STATUS_SEALED,
        "pack_mode": box.pack_mode or "ship",
        "shipment_id": box.shipment_id,
        "ship_date": box.ship_date or "",
        "created_at": box.created_at.isoformat(sep=" ", timespec="seconds") if box.created_at else None,
        "label_printed_at": box.label_printed_at.isoformat(sep=" ", timespec="seconds")
        if getattr(box, "label_printed_at", None)
        else None,
        "label_printed_by": getattr(box, "label_printed_by", None) or "",
        "printed": bool(getattr(box, "label_printed_at", None)),
        "trace_url": box_trace_url(box.box_no),
        "full": bool(target and int(filled) >= target),
    }
    if with_codes:
        rows = (
            db.query(OrderScan)
            .filter(OrderScan.box_id == box.id)
            .order_by(OrderScan.id.asc())
            .all()
        )
        data["barcodes"] = [s.barcode for s in rows]
    return data


def get_open_pack_box(db: Session, line_key: str) -> Optional[ShipmentBox]:
    key = (line_key or "").strip()
    if not key:
        return None
    return (
        db.query(ShipmentBox)
        .filter(
            ShipmentBox.line_key == key,
            ShipmentBox.status == BOX_STATUS_OPEN,
            ShipmentBox.pack_mode == "scan",
        )
        .order_by(ShipmentBox.id.desc())
        .first()
    )


def open_pack_box(db: Session, *, line_key: str, qty_target: int, operator: str = "") -> dict:
    order = get_order_or_404(db, line_key)
    target = int(qty_target or 0)
    if target < 1:
        raise ValueError("每箱数量须大于 0")
    existing = get_open_pack_box(db, order.line_key)
    if existing:
        raise ValueError(f"已有未封箱 {existing.box_no}（{existing.qty}/{existing.qty_target}），请先封箱或继续往这箱扫")
    sealed_n = (
        db.query(func.count(ShipmentBox.id))
        .filter(ShipmentBox.line_key == order.line_key, ShipmentBox.pack_mode == "scan")
        .scalar()
        or 0
    )
    box = ShipmentBox(
        box_no=_next_box_no(db),
        shipment_id=None,
        slip_id=None,
        line_key=order.line_key,
        purchase_no=order.purchase_no or "",
        product_goods_no=order.product_goods_no,
        product_goods_name=order.product_goods_name,
        customer_name=order.customer_name,
        box_index=int(sealed_n) + 1,
        box_count=0,
        qty=0,
        qty_target=target,
        status=BOX_STATUS_OPEN,
        pack_mode="scan",
        ship_date="",
        created_at=datetime.utcnow(),
    )
    db.add(box)
    db.flush()
    append_scan_log(
        {
            "event": "box_open",
            "box_no": box.box_no,
            "line_key": order.line_key,
            "qty_target": target,
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _box_payload(db, box, with_codes=True)


def seal_pack_box(db: Session, *, box_id: int, operator: str = "") -> dict:
    box = db.query(ShipmentBox).filter(ShipmentBox.id == int(box_id)).first()
    if not box:
        raise ValueError("箱子不存在")
    if box.status != BOX_STATUS_OPEN:
        raise ValueError("该箱已封箱")
    filled = (
        db.query(func.count(OrderScan.id)).filter(OrderScan.box_id == box.id).scalar() or 0
    )
    if int(filled) < 1:
        raise ValueError("箱子是空的，请先扫板再封箱")
    box.qty = int(filled)
    box.status = BOX_STATUS_SEALED
    db.flush()
    append_scan_log(
        {
            "event": "box_seal",
            "box_no": box.box_no,
            "line_key": box.line_key,
            "qty": box.qty,
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _box_payload(db, box, with_codes=True)


def resume_pack_box(db: Session, *, box_id: int, operator: str = "") -> dict:
    """未装满的箱子可再打开继续扫。不改 register_scan 写库。"""
    box = db.query(ShipmentBox).filter(ShipmentBox.id == int(box_id)).first()
    if not box:
        raise ValueError("箱子不存在")
    if (box.pack_mode or "") != "scan":
        raise ValueError("只能继续扫码入箱记录")
    st = (box.status or "").strip()
    if box.shipment_id or st in (BOX_STATUS_AWAITING, BOX_STATUS_SHIPPED):
        raise ValueError("已发货的箱子不能再入箱")
    filled = (
        db.query(func.count(OrderScan.id)).filter(OrderScan.box_id == box.id).scalar() or 0
    )
    target = int(box.qty_target or 0)
    if target and int(filled) >= target:
        raise ValueError(f"{box.box_no} 已满 {target} 片，请开新箱")
    other = get_open_pack_box(db, box.line_key)
    if other and other.id != box.id:
        raise ValueError(
            f"该订单还有装箱中的 {other.box_no}（{other.qty}/{other.qty_target}），"
            "请先封箱或先继续那一箱"
        )
    if st == BOX_STATUS_OPEN:
        return _box_payload(db, box, with_codes=True)
    if st != BOX_STATUS_SEALED:
        raise ValueError("该箱当前状态不能继续入箱")
    box.status = BOX_STATUS_OPEN
    box.qty = int(filled)
    db.flush()
    append_scan_log(
        {
            "event": "box_resume",
            "box_no": box.box_no,
            "line_key": box.line_key,
            "qty": int(filled),
            "qty_target": target,
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _box_payload(db, box, with_codes=True)


def delete_pack_box(db: Session, *, box_id: int, operator: str = "") -> dict:
    """删除扫码入箱记录。不删入库板码，只解开箱绑定。已发货须先撤销。"""
    box = db.query(ShipmentBox).filter(ShipmentBox.id == int(box_id)).first()
    if not box:
        raise ValueError("箱子不存在")
    if (box.pack_mode or "") != "scan":
        raise ValueError("只能删除扫码入箱记录")
    st = (box.status or "").strip()
    if box.shipment_id or st in (BOX_STATUS_AWAITING, BOX_STATUS_SHIPPED):
        raise ValueError("已发货的箱子请先到成品发货撤销后再删除")
    filled = (
        db.query(func.count(OrderScan.id)).filter(OrderScan.box_id == box.id).scalar() or 0
    )
    info = {
        "id": box.id,
        "box_no": box.box_no,
        "line_key": box.line_key,
        "purchase_no": box.purchase_no or "",
        "qty": int(filled),
    }
    db.query(OrderScan).filter(OrderScan.box_id == box.id).update(
        {OrderScan.box_id: None},
        synchronize_session=False,
    )
    db.delete(box)
    db.flush()
    append_scan_log(
        {
            "event": "box_delete",
            "box_no": info["box_no"],
            "line_key": info["line_key"],
            "qty": info["qty"],
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return info


def delete_inbound_scan_by_barcode(db: Session, *, barcode: str, operator: str = "") -> dict:
    """删除一片的入库，并从所在箱拿掉。不改产线过站，不改 register_scan。空箱才删箱。"""
    scan = _find_scan_by_barcode(db, barcode)
    if not scan:
        raise ValueError("未找到该编码（未入库）")
    st = (scan.status or "").strip()
    if st in (SCAN_STATUS_AWAITING, SCAN_STATUS_SHIPPED) or scan.shipment_id:
        raise ValueError("该板码已发货，请先到成品发货撤销后再删除")
    box = None
    if scan.box_id:
        box = db.query(ShipmentBox).filter(ShipmentBox.id == int(scan.box_id)).first()
    if box:
        bst = (box.status or "").strip()
        if box.shipment_id or bst in (BOX_STATUS_AWAITING, BOX_STATUS_SHIPPED):
            raise ValueError("已发货的箱子请先到成品发货撤销后再删除")
    info = {
        "barcode": scan.barcode,
        "line_key": scan.line_key,
        "purchase_no": scan.purchase_no or "",
        "box_no": box.box_no if box else "",
        "box_deleted": False,
        "box_remaining": 0,
    }
    db.delete(scan)
    db.flush()
    if box:
        remaining = (
            db.query(func.count(OrderScan.id)).filter(OrderScan.box_id == box.id).scalar() or 0
        )
        info["box_remaining"] = int(remaining)
        if int(remaining) <= 0:
            db.delete(box)
            info["box_deleted"] = True
        else:
            box.qty = int(remaining)
    append_scan_log(
        {
            "event": "scan_delete",
            "barcode": info["barcode"],
            "line_key": info["line_key"],
            "purchase_no": info["purchase_no"],
            "box_no": info["box_no"],
            "box_deleted": info["box_deleted"],
            "box_remaining": info["box_remaining"],
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    db.flush()
    return info


def _find_scan_by_barcode(db: Session, keyword: str) -> Optional[OrderScan]:
    text = (keyword or "").strip()
    if not text:
        return None
    # 扫枪常把 D0 扫成 DO
    if text.upper().startswith("DO") and len(text) > 2 and text[2].isdigit():
        text = "D0" + text[2:]
    row = db.query(OrderScan).filter(OrderScan.barcode == text).first()
    if row:
        return row
    row = (
        db.query(OrderScan)
        .filter(func.lower(OrderScan.barcode) == text.lower())
        .first()
    )
    if row:
        return row
    # 扫枪漏位时整码对不上，用末尾日期+流水唯一定位
    for n in (11, 10, 5):
        if len(text) < n:
            continue
        suffix = text[-n:]
        rows = (
            db.query(OrderScan)
            .filter(OrderScan.barcode.like(f"%{suffix}"))
            .order_by(OrderScan.id.desc())
            .limit(8)
            .all()
        )
        if len(rows) == 1:
            return rows[0]
        boxed = [r for r in rows if r.box_id]
        if len(boxed) == 1:
            return boxed[0]
    return None


def pack_box_barcode_hint(db: Session, keyword: str) -> dict:
    scan = _find_scan_by_barcode(db, keyword)
    if not scan:
        return {}
    if not scan.box_id:
        return {
            "matched_barcode": scan.barcode,
            "matched_box_no": None,
            "barcode_hint": f"板码 {scan.barcode} 已入库，但还没有入箱",
        }
    box = db.query(ShipmentBox).filter(ShipmentBox.id == int(scan.box_id)).first()
    if not box:
        return {
            "matched_barcode": scan.barcode,
            "matched_box_no": None,
            "barcode_hint": f"板码 {scan.barcode} 已入库，但还没有入箱",
        }
    return {
        "matched_barcode": scan.barcode,
        "matched_box_no": box.box_no,
        "barcode_hint": f"板码 {scan.barcode} 在箱 {box.box_no}",
    }


_BOX_STATUS_LABELS = {
    BOX_STATUS_OPEN: "装箱中",
    BOX_STATUS_SEALED: "已封待发",
    BOX_STATUS_AWAITING: "已发待审",
    BOX_STATUS_SHIPPED: "已发货",
}


def lookup_pack_box_query(db: Session, raw: str) -> dict:
    """PDA 查箱号：扫板码或箱号，只读，不写库。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("请扫描板码")
    box = db.query(ShipmentBox).filter(ShipmentBox.box_no == text).first()
    if not box:
        up = text.upper()
        if up.startswith("BX"):
            box = db.query(ShipmentBox).filter(ShipmentBox.box_no == up).first()
    matched = ""
    if not box:
        scan = _find_scan_by_barcode(db, text)
        if not scan:
            raise ValueError("未找到该编码（未入库或未入箱）")
        matched = scan.barcode or text
        if not scan.box_id:
            raise ValueError("该板码已入库，但还没有入箱")
        box = db.query(ShipmentBox).filter(ShipmentBox.id == int(scan.box_id)).first()
        if not box:
            raise ValueError("该板码已入库，但还没有入箱")
    filled = (
        db.query(func.count(OrderScan.id)).filter(OrderScan.box_id == box.id).scalar() or 0
    )
    st = (box.status or "").strip()
    return {
        "box_no": box.box_no,
        "qty": int(filled),
        "qty_target": int(box.qty_target or box.qty or 0),
        "status": st,
        "status_label": _BOX_STATUS_LABELS.get(st, st or "—"),
        "purchase_no": box.purchase_no or "",
        "goods_no": box.product_goods_no or "",
        "goods_name": box.product_goods_name or "",
        "matched_barcode": matched or text,
    }


def attach_inbound_barcode_to_open_box(
    db: Session, *, barcode: str, line_key: str = ""
) -> Tuple[OrderScan, dict]:
    """已入库散板再扫一次，只补入当前开箱。不改 register_scan。"""
    scan = _find_scan_by_barcode(db, barcode)
    if not scan:
        raise ValueError("未找到该编码（未入库）")
    st = (scan.status or "").strip()
    if st != SCAN_STATUS_PENDING:
        raise ValueError("该条码已发货或待审核，不能再入箱")
    if scan.box_id:
        box = db.query(ShipmentBox).filter(ShipmentBox.id == int(scan.box_id)).first()
        raise ValueError(f"该条码已在箱 {box.box_no if box else scan.box_id}")
    info = attach_scan_to_open_box(db, scan, line_key=scan.line_key or line_key)
    return scan, info


def attach_scan_to_open_box(db: Session, scan: OrderScan, *, line_key: str) -> dict:
    """扫码成功后挂到当前开着的箱。不改 register_scan 写库。"""
    box = get_open_pack_box(db, line_key or scan.line_key)
    if not box:
        raise ValueError("请先开箱，再往这只箱子里扫板")
    filled = (
        db.query(func.count(OrderScan.id)).filter(OrderScan.box_id == box.id).scalar() or 0
    )
    target = int(box.qty_target or 0)
    if target and int(filled) >= target:
        raise ValueError(f"本箱已满 {target} 片，请先封箱或开新箱")
    scan.box_id = box.id
    box.qty = int(filled) + 1
    sealed = False
    if target and box.qty >= target:
        box.status = BOX_STATUS_SEALED
        sealed = True
        append_scan_log(
            {
                "event": "box_seal",
                "auto": True,
                "box_no": box.box_no,
                "line_key": box.line_key,
                "qty": box.qty,
                "at": datetime.utcnow().isoformat(),
            }
        )
    db.flush()
    payload = _box_payload(db, box, with_codes=False)
    payload["sealed"] = sealed
    return payload


def absorb_loose_pending_into_box(
    db: Session,
    *,
    box_id: int,
    operator: str = "",
) -> dict:
    """把本单未入箱散板并入当前开着的箱。不改 register_scan，只补 box_id。"""
    box = db.query(ShipmentBox).filter(ShipmentBox.id == int(box_id)).first()
    if not box:
        raise ValueError("箱子不存在")
    if (box.pack_mode or "") != "scan":
        raise ValueError("只能把散板并入扫码入箱")
    if (box.status or "").strip() != BOX_STATUS_OPEN:
        raise ValueError("请先继续入箱，再并入散板")
    filled = int(
        db.query(func.count(OrderScan.id)).filter(OrderScan.box_id == box.id).scalar() or 0
    )
    target = int(box.qty_target or 0)
    if target and filled >= target:
        raise ValueError(f"本箱已满 {target} 片，请先封箱或开新箱")
    room = (target - filled) if target else 10_000
    if room < 1:
        raise ValueError("本箱没有空位")
    q = (
        db.query(OrderScan)
        .filter(
            OrderScan.line_key == box.line_key,
            OrderScan.status == SCAN_STATUS_PENDING,
            OrderScan.box_id.is_(None),
            ~OrderScan.barcode.like(f"{BACKFILL_BARCODE_PREFIX}%"),
        )
        .order_by(OrderScan.id.asc())
    )
    loose = q.limit(int(room)).all()
    if not loose:
        raise ValueError("没有未入箱的散板")
    for scan in loose:
        scan.box_id = box.id
    absorbed = len(loose)
    box.qty = filled + absorbed
    db.flush()
    sealed = False
    if target and box.qty >= target:
        box.status = BOX_STATUS_SEALED
        sealed = True
        append_scan_log(
            {
                "event": "box_seal",
                "auto": True,
                "reason": "absorb_loose",
                "box_no": box.box_no,
                "line_key": box.line_key,
                "qty": box.qty,
                "at": datetime.utcnow().isoformat(),
            }
        )
    remaining = count_loose_pending(db, box.line_key)
    append_scan_log(
        {
            "event": "box_absorb_loose",
            "box_no": box.box_no,
            "line_key": box.line_key,
            "absorbed": absorbed,
            "remaining_loose": remaining,
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    db.flush()
    payload = _box_payload(db, box, with_codes=True)
    payload["sealed"] = sealed
    payload["absorbed"] = absorbed
    payload["remaining_loose"] = remaining
    return payload


def list_pack_boxes(
    db: Session,
    *,
    line_key: str = "",
    line_keys: Optional[list[str]] = None,
    status: str = "",
    available: bool = False,
    scan_only: bool = False,
    keyword: str = "",
    limit: int = 300,
) -> list[dict]:
    q = db.query(ShipmentBox)
    keys = [k for k in (line_keys or []) if (k or "").strip()]
    key = (line_key or "").strip()
    if keys:
        q = q.filter(ShipmentBox.line_key.in_(keys))
    elif key:
        q = q.filter(ShipmentBox.line_key == key)
    elif not scan_only:
        return []
    if scan_only:
        q = q.filter(ShipmentBox.pack_mode == "scan")
    if available:
        q = q.filter(
            ShipmentBox.status == BOX_STATUS_SEALED,
            ShipmentBox.shipment_id.is_(None),
            ShipmentBox.pack_mode == "scan",
        )
    else:
        st = (status or "").strip()
        if st:
            q = q.filter(ShipmentBox.status == st)
    kw = (keyword or "").strip()
    hit_box = None
    scan_hit = _find_scan_by_barcode(db, kw) if kw else None
    if scan_hit and scan_hit.box_id:
        cand = db.query(ShipmentBox).filter(ShipmentBox.id == int(scan_hit.box_id)).first()
        if cand and (not scan_only or (cand.pack_mode or "") == "scan"):
            hit_box = cand
    if kw:
        like = f"%{kw}%"
        barcode_match = or_(
            OrderScan.barcode == kw,
            func.lower(OrderScan.barcode) == kw.lower(),
        )
        if len(kw) >= 6:
            barcode_match = or_(barcode_match, OrderScan.barcode.like(like))
        barcode_ids = (
            db.query(OrderScan.box_id)
            .filter(OrderScan.box_id.isnot(None), barcode_match)
        )
        q = q.filter(
            or_(
                ShipmentBox.box_no.like(like),
                ShipmentBox.purchase_no.like(like),
                ShipmentBox.product_goods_no.like(like),
                ShipmentBox.product_goods_name.like(like),
                ShipmentBox.id.in_(barcode_ids),
            )
        )
    cap = max(1, min(int(limit or 300), 1000))
    rows = q.order_by(ShipmentBox.id.desc()).limit(cap).all()
    if hit_box:
        rows = [hit_box] + [b for b in rows if b.id != hit_box.id]
    return [_box_payload(db, b) for b in rows]


def count_loose_pending(db: Session, line_key: str) -> int:
    key = (line_key or "").strip()
    if not key:
        return 0
    return int(
        db.query(func.count(OrderScan.id))
        .filter(
            OrderScan.line_key == key,
            OrderScan.status == SCAN_STATUS_PENDING,
            OrderScan.box_id.is_(None),
        )
        .scalar()
        or 0
    )


def pack_box_station_state(db: Session, line_key: str) -> dict:
    key = (line_key or "").strip()
    box = get_open_pack_box(db, key)
    all_boxes = list_pack_boxes(db, line_key=key)
    records = [b for b in all_boxes if (b.get("pack_mode") or "") == "scan"]
    return {
        "box": _box_payload(db, box, with_codes=True) if box else None,
        "sealed_boxes": list_pack_boxes(db, line_key=key, available=True),
        "records": records,
        "loose_pending": count_loose_pending(db, key),
    }


def _qr_png_data_url(text: str) -> str:
    payload = (text or "").strip() or " "
    try:
        import base64
        from io import BytesIO

        import qrcode

        qr = qrcode.QRCode(border=1, box_size=4)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def is_backfill_scan(scan: OrderScan) -> bool:
    bc = (scan.barcode or "").strip()
    op = (scan.operator or "").strip()
    return bc.startswith(BACKFILL_BARCODE_PREFIX) or op.startswith(BACKFILL_OPERATOR_PREFIX)


def is_backfill_shipment(shipment: Shipment) -> bool:
    remark = (shipment.remark or "").strip()
    op = (shipment.operator or "").strip()
    return remark.startswith(BACKFILL_REMARK_TAG) or op.startswith(BACKFILL_OPERATOR_PREFIX)


def detect_code_type(barcode: str) -> str:
    text = (barcode or "").strip()
    if not text:
        return "unknown"
    if text.isdigit() and len(text) >= 12:
        return "1d"
    return "qr"


def append_scan_log(record: dict) -> None:
    SCAN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    daily = SCAN_LOG_DIR / f"scans_{datetime.now().strftime('%Y%m%d')}.jsonl"
    with open(daily, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_scan_stats(
    db: Session,
    line_keys: list[str],
    *,
    exclude_legacy: bool = True,
) -> Dict[str, Dict[str, int]]:
    """按订单行统计包装扫码。

    exclude_legacy=True（默认）：不计旧站迁移（operator 以 legacy: 开头），
    避免历史数据当成「现在的入库/已发」。
    """
    if not line_keys:
        return {}
    from sqlalchemy import or_

    q = db.query(
        OrderScan.line_key,
        OrderScan.status,
        func.count(OrderScan.id),
    ).filter(OrderScan.line_key.in_(line_keys))
    if exclude_legacy:
        q = q.filter(
            or_(OrderScan.operator.is_(None), ~OrderScan.operator.like("legacy:%"))
        )
    # 补录合成条码不按片计数，改由补录出库单 qty 计入（避免几十万假码）
    q = q.filter(~OrderScan.barcode.like(f"{BACKFILL_BARCODE_PREFIX}%"))
    rows = q.group_by(OrderScan.line_key, OrderScan.status).all()
    stats: Dict[str, Dict[str, int]] = {}
    for line_key, status, count in rows:
        bucket = stats.setdefault(
            line_key, {"pending": 0, "awaiting": 0, "shipped": 0}
        )
        st = (status or "").strip()
        if st == SCAN_STATUS_AWAITING:
            bucket["awaiting"] = int(count)
        elif st == SCAN_STATUS_SHIPPED:
            bucket["shipped"] = int(count)
        elif st == SCAN_STATUS_PENDING:
            bucket["pending"] = int(count)
        else:
            # 未知状态并入 pending 以免丢数
            bucket["pending"] = int(bucket.get("pending") or 0) + int(count)
    bf_rows = (
        db.query(Shipment.line_key, func.coalesce(func.sum(Shipment.qty), 0))
        .filter(
            Shipment.line_key.in_(line_keys),
            or_(
                Shipment.operator.like(f"{BACKFILL_OPERATOR_PREFIX}%"),
                Shipment.remark.like(f"{BACKFILL_REMARK_TAG}%"),
            ),
        )
        .group_by(Shipment.line_key)
        .all()
    )
    for line_key, qty in bf_rows:
        bucket = stats.setdefault(
            line_key, {"pending": 0, "awaiting": 0, "shipped": 0}
        )
        bucket["shipped"] = int(bucket.get("shipped") or 0) + int(qty or 0)
    return stats


def get_order_or_404(db: Session, line_key: str) -> SrmOrder:
    order = db.query(SrmOrder).filter(SrmOrder.line_key == line_key).first()
    if not order:
        raise ValueError("订单不存在")
    return order


def register_scan(
    db: Session,
    *,
    line_key: str,
    barcode: str,
    code_type: Optional[str] = None,
    operator: str = "",
) -> Tuple[OrderScan, Dict[str, int]]:
    raw = (barcode or "").strip()
    if not raw:
        raise ValueError("条码不能为空")
    if len(raw) > 128:
        raise ValueError("条码过长")

    order = get_order_or_404(db, line_key)
    if order.is_completed:
        raise ValueError("订单已结案，不能继续扫码")

    # 残码/半截码直接拦截，不计入库
    barcode = validate_packing_barcode(
        db,
        raw,
        customer_id=(order.customer_id or "").strip(),
        purchase_no=(order.purchase_no or "").strip(),
        line_key=line_key,
    )

    # 权威：条码按镭雕登记表对应订单行；与选中行冲突时硬拦（不再静默改行）
    selected_model = (order.product_goods_no or "").strip()
    selected_pn = (order.purchase_no or "").strip()
    laser_order, laser_batch, laser_err = resolve_packing_line_by_laser(
        db, barcode=barcode, selected_line_key=line_key
    )
    if laser_err:
        raise ValueError(laser_err)
    if laser_order is not None:
        order = laser_order
        line_key = order.line_key

    # 防串机型：对照「操作员选中的行」（勿用纠正后的行，否则同单错机型会被放过）
    gate = check_packing_gate(
        db,
        barcode,
        model_code=selected_model or (order.product_goods_no or "").strip(),
        customer_id=(order.customer_id or "").strip(),
        purchase_no=selected_pn or (order.purchase_no or "").strip(),
    )
    if not gate.get("ok"):
        raise ValueError(gate.get("message") or "工序卡控未通过")

    existing = db.query(OrderScan).filter(OrderScan.barcode == barcode).first()
    if existing:
        if existing.line_key == line_key:
            raise ValueError("该条码已扫过")
        raise ValueError(f"该条码已属于其他订单（{existing.line_key}）")

    pending = (
        db.query(func.count(OrderScan.id))
        .filter(OrderScan.line_key == line_key, OrderScan.status == SCAN_STATUS_PENDING)
        .scalar()
        or 0
    )
    order_qty = int(order.batch_pur_qty or order.output_qty or 0)
    if order_qty > 0 and pending >= order_qty:
        raise ValueError(f"已达订单量 {order_qty}，请先发货或检查是否扫错单")

    resolved_type = (code_type or detect_code_type(barcode)).strip() or "unknown"
    scan = OrderScan(
        line_key=line_key,
        purchase_no=order.purchase_no,
        barcode=barcode,
        code_type=resolved_type,
        status=SCAN_STATUS_PENDING,
        operator=(operator or "").strip() or None,
        scanned_at=datetime.utcnow(),
    )
    db.add(scan)
    db.flush()
    # 完整码入库后清掉同单半截残码（不计发货）
    purge_truncated_suffixes(
        db,
        barcode,
        purchase_no=(order.purchase_no or "").strip(),
        line_key=line_key,
        model="order_scan",
    )
    db.flush()

    stats = get_scan_stats(db, [line_key]).get(line_key, {"pending": 0, "shipped": 0})
    # flush 后 get_scan_stats 已含本条，勿再 +1（否则弹窗会多显示 1）
    pending_now = int(stats.get("pending", 0) or 0)
    shipped_now = int(stats.get("shipped", 0) or 0)
    append_scan_log(
        {
            "event": "scan",
            "line_key": line_key,
            "purchase_no": order.purchase_no,
            "barcode": barcode,
            "code_type": resolved_type,
            "operator": operator,
            "pending_qty": pending_now,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return scan, {
        "pending": pending_now,
        "shipped": shipped_now,
        "line_key": line_key,
        "purchase_no": order.purchase_no or "",
        "product_goods_no": (order.product_goods_no or "").strip(),
    }


def _next_shipment_no(db: Session) -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"SH-{today}-"
    last = (
        db.query(Shipment)
        .filter(Shipment.shipment_no.like(f"{prefix}%"))
        .order_by(Shipment.id.desc())
        .first()
    )
    last_slip = (
        db.query(ShipmentSlip)
        .filter(ShipmentSlip.slip_no.like(f"{prefix}%"))
        .order_by(ShipmentSlip.id.desc())
        .first()
    )
    seq = 1
    for row_no in (
        last.shipment_no if last else None,
        last_slip.slip_no if last_slip else None,
    ):
        if not row_no:
            continue
        try:
            # SH-YYYYMMDD-001 or SH-YYYYMMDD-001-02
            parts = row_no.split("-")
            seq = max(seq, int(parts[2]) + 1)
        except (ValueError, IndexError):
            pass
    return f"{prefix}{seq:03d}"


def create_shipment(
    db: Session,
    *,
    line_key: str,
    ship_date: str,
    box_count: int = 1,
    qty_per_box: int = 1,
    qty: Optional[int] = None,
    logistics: str = "",
    remark: str = "",
    operator: str = "",
    slip_id: Optional[int] = None,
    shipment_no: Optional[str] = None,
    auto_approve: bool = False,
    approved_by: str = "",
    box_ids: Optional[list[int]] = None,
    pack_specs: Optional[list] = None,
    remainder_qty: int = 0,
) -> Shipment:
    """创建出库单。

    默认 auto_approve=False：扫码进入 awaiting_approve，出库单 approval_status=pending，
    须 dxgc/dxgc002/WGQ 确认后才计入已发货。不影响 register_scan。
    """
    order = get_order_or_404(db, line_key)
    pack_boxes: list[ShipmentBox] = []
    box_qtys: Optional[list[int]] = None
    extra_loose: list[OrderScan] = []
    id_list = [int(x) for x in (box_ids or []) if int(x) > 0]
    if id_list:
        pack_boxes = (
            db.query(ShipmentBox)
            .filter(ShipmentBox.id.in_(id_list))
            .order_by(ShipmentBox.id.asc())
            .all()
        )
        if len(pack_boxes) != len(set(id_list)):
            raise ValueError("所选箱子不存在")
        for b in pack_boxes:
            if b.line_key != line_key:
                raise ValueError(f"箱子 {b.box_no} 不属于本订单")
            if b.status != BOX_STATUS_SEALED:
                raise ValueError(f"箱子 {b.box_no} 不是已封箱待发（当前 {b.status}）")
            if b.shipment_id:
                raise ValueError(f"箱子 {b.box_no} 已在出库单中")
        pending_scans = (
            db.query(OrderScan)
            .filter(
                OrderScan.line_key == line_key,
                OrderScan.status == SCAN_STATUS_PENDING,
                OrderScan.box_id.in_([b.id for b in pack_boxes]),
            )
            .order_by(OrderScan.id.asc())
            .all()
        )
        if not pending_scans:
            raise ValueError("所选箱子没有待发板码")
        ship_n = len(pending_scans)
        to_ship = list(pending_scans)
        boxes_n = len(pack_boxes)
        extra_loose: list[OrderScan] = []
        try:
            rem_n = int(remainder_qty or 0)
        except (TypeError, ValueError):
            rem_n = 0
        if rem_n > 0:
            extra_loose = (
                db.query(OrderScan)
                .filter(
                    OrderScan.line_key == line_key,
                    OrderScan.status == SCAN_STATUS_PENDING,
                    OrderScan.box_id.is_(None),
                )
                .order_by(OrderScan.id.asc())
                .limit(rem_n)
                .all()
            )
            if len(extra_loose) < rem_n:
                raise ValueError(
                    f"尾数 {rem_n} 超过散板待发 {len(extra_loose)}"
                )
            to_ship = to_ship + extra_loose
            ship_n = len(to_ship)
            boxes_n = len(pack_boxes) + 1
        box_qty_list = [int(b.qty or 0) for b in pack_boxes]
        if extra_loose:
            box_qty_list.append(len(extra_loose))
        per_n = _typical_qty_per_box(box_qty_list)
        note = format_pack_note_from_qtys(box_qty_list)
        if note and "装箱" not in (remark or ""):
            base = (remark or "").strip()
            remark = f"{base}；{note}" if base else note
    else:
        pending_scans = (
            db.query(OrderScan)
            .filter(
                OrderScan.line_key == line_key,
                OrderScan.status == SCAN_STATUS_PENDING,
                OrderScan.box_id.is_(None),
            )
            .order_by(OrderScan.id.asc())
            .all()
        )
        if not pending_scans:
            raise ValueError("没有待发的散板（已封箱请勾选箱子发货）")

        pending_n = len(pending_scans)
        if qty is None or int(qty) <= 0:
            ship_n = pending_n
        else:
            ship_n = int(qty)
            if ship_n > pending_n:
                raise ValueError(f"出货数 {ship_n} 超过已入库待出 {pending_n}")
        to_ship = pending_scans[:ship_n]
        spec_rows = [s for s in (pack_specs or []) if isinstance(s, dict)]
        if spec_rows or int(remainder_qty or 0) > 0:
            try:
                rem_n = int(remainder_qty or 0)
            except (TypeError, ValueError):
                rem_n = 0
            box_qtys = expand_pack_specs(spec_rows, rem_n)
            packed_n = sum(box_qtys)
            if packed_n != ship_n:
                raise ValueError(
                    f"各棉片数+尾数 {packed_n} 与发货数 {ship_n} 不一致"
                )
            boxes_n = len(box_qtys)
            pers = []
            for s in spec_rows:
                try:
                    if int(s.get("qty") or 0) > 0:
                        pers.append(int(s.get("qty_per_box") or s.get("per") or 0))
                except (TypeError, ValueError):
                    continue
            per_n = max(pers) if pers else 1
            note = format_pack_note(spec_rows, rem_n)
            if note:
                base = (remark or "").strip()
                remark = f"{base}；{note}" if base else note
        else:
            boxes_n = max(int(box_count or 1), 1)
            try:
                per_n = int(qty_per_box or 0)
            except (TypeError, ValueError):
                per_n = 0
            if per_n < 1:
                per_n = ship_n if boxes_n <= 1 else max(1, (ship_n + boxes_n - 1) // boxes_n)
            expand_box_qtys(ship_n, boxes_n, per_n)

    now = datetime.utcnow()
    if auto_approve:
        approval = SHIP_APPROVAL_APPROVED
        scan_status = SCAN_STATUS_SHIPPED
        appr_by = (approved_by or operator or "").strip() or None
        appr_at = now
    else:
        approval = SHIP_APPROVAL_PENDING
        scan_status = SCAN_STATUS_AWAITING
        appr_by = None
        appr_at = None

    shipment = Shipment(
        shipment_no=(shipment_no or "").strip() or _next_shipment_no(db),
        slip_id=int(slip_id) if slip_id else None,
        line_key=line_key,
        purchase_no=order.purchase_no,
        customer_name=order.customer_name,
        product_goods_no=order.product_goods_no,
        product_goods_name=order.product_goods_name,
        qty=ship_n,
        ship_date=ship_date,
        box_count=boxes_n,
        qty_per_box=per_n,
        logistics=(logistics or "").strip() or None,
        remark=(remark or "").strip() or None,
        operator=(operator or "").strip() or None,
        approval_status=approval,
        approved_by=appr_by,
        approved_at=appr_at,
        created_at=now,
    )
    db.add(shipment)
    db.flush()

    for scan in to_ship:
        scan.status = scan_status
        scan.shipment_id = shipment.id
        scan.shipped_at = now if auto_approve else None
    if pack_boxes:
        box_status = BOX_STATUS_SHIPPED if auto_approve else BOX_STATUS_AWAITING
        for b in pack_boxes:
            b.shipment_id = shipment.id
            b.slip_id = int(slip_id) if slip_id else b.slip_id
            b.ship_date = ship_date
            b.status = box_status
        if extra_loose:
            rem_box = ShipmentBox(
                box_no=_next_box_no(db),
                shipment_id=shipment.id,
                slip_id=int(slip_id) if slip_id else None,
                line_key=line_key,
                purchase_no=order.purchase_no or "",
                product_goods_no=order.product_goods_no,
                product_goods_name=order.product_goods_name,
                customer_name=order.customer_name,
                box_index=len(pack_boxes) + 1,
                box_count=int(boxes_n),
                qty=len(extra_loose),
                qty_target=len(extra_loose),
                status=box_status,
                pack_mode="ship",
                ship_date=ship_date or "",
                created_at=now,
            )
            db.add(rem_box)
            db.flush()
            for s in extra_loose:
                s.box_id = rem_box.id
    else:
        _create_boxes_for_shipment(db, shipment, to_ship, box_qtys=box_qtys)

    append_scan_log(
        {
            "event": "ship",
            "shipment_no": shipment.shipment_no,
            "slip_id": shipment.slip_id,
            "line_key": line_key,
            "purchase_no": order.purchase_no,
            "qty": ship_n,
            "operator": operator,
            "approval_status": approval,
            "at": now.isoformat(),
        }
    )
    return shipment


def create_multi_shipment(
    db: Session,
    *,
    customer_id: str,
    ship_date: str,
    lines: list[dict],
    logistics: str = "",
    remark: str = "",
    operator: str = "",
) -> dict:
    """同客户多订单合并发货：手填每单数量，不得超过该单待发。

    lines: [{line_key, qty, box_count?, qty_per_box?, pack_specs?, remainder_qty?}]
    不改扫码入库逻辑，仅消费 pending 扫码。
    """
    cid = (customer_id or "").strip()
    if not cid:
        raise ValueError("请指定客户")
    if not lines:
        raise ValueError("请至少选择一个订单并填写发货数量")

    # 规范化并校验
    normalized: list[tuple[SrmOrder, int, int, int, list[int], list[dict], int]] = []
    seen: set[str] = set()
    for raw in lines:
        key = str((raw or {}).get("line_key") or "").strip()
        if not key:
            raise ValueError("存在空的订单行")
        if key in seen:
            raise ValueError(f"订单行重复：{key}")
        seen.add(key)
        raw_ids = (raw or {}).get("box_ids") or []
        box_id_list: list[int] = []
        for x in raw_ids:
            try:
                n = int(x)
            except (TypeError, ValueError):
                continue
            if n > 0:
                box_id_list.append(n)
        try:
            qty = int((raw or {}).get("qty") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"发货数量无效：{key}") from exc
        try:
            boxes = int((raw or {}).get("box_count") or 1)
        except (TypeError, ValueError):
            boxes = 1
        try:
            per = int((raw or {}).get("qty_per_box") or 0)
        except (TypeError, ValueError):
            per = 0
        spec_rows: list[dict] = []
        for s in (raw or {}).get("pack_specs") or []:
            if not isinstance(s, dict):
                continue
            try:
                spec_rows.append(
                    {
                        "qty": int(s.get("qty") or 0),
                        "qty_per_box": int(s.get("qty_per_box") or s.get("per") or 0),
                        "box_count": int(s.get("box_count") or 0),
                    }
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"订单装箱规格无效：{key}") from exc
        try:
            rem = int((raw or {}).get("remainder_qty") or 0)
        except (TypeError, ValueError):
            rem = 0
        order = get_order_or_404(db, key)
        ocid = (order.customer_id or "").strip()
        if ocid != cid:
            raise ValueError(
                f"订单 {order.purchase_no} 客户不一致（要求同一客户合并发货）"
            )
        if order.is_completed:
            raise ValueError(f"订单 {order.purchase_no} 已结案，不能发货")
        if box_id_list:
            sealed = (
                db.query(ShipmentBox)
                .filter(ShipmentBox.id.in_(box_id_list), ShipmentBox.line_key == key)
                .all()
            )
            if len(sealed) != len(set(box_id_list)):
                raise ValueError(f"订单 {order.purchase_no} 所选箱子无效")
            qty = sum(int(b.qty or 0) for b in sealed)
            boxes = len(sealed)
            per = _typical_qty_per_box([int(b.qty or 0) for b in sealed])
            spec_rows = []
            if rem < 0:
                rem = 0
            if rem > 0:
                pending_n = count_loose_pending(db, key)
                if rem > int(pending_n):
                    raise ValueError(
                        f"订单 {order.purchase_no} 尾数 {rem} 超过散板待发 {pending_n}"
                    )
                qty += rem
                boxes += 1
            if qty <= 0:
                raise ValueError(f"订单 {order.purchase_no} 所选箱子数量为 0")
        else:
            if qty <= 0:
                raise ValueError(f"发货数量须大于 0：{key}")
            pending_n = count_loose_pending(db, key)
            if qty > int(pending_n):
                raise ValueError(
                    f"订单 {order.purchase_no} 出货数 {qty} 超过散板待发 {pending_n}（已封箱请勾选箱子）"
                )
            if spec_rows or rem:
                try:
                    qtys = expand_pack_specs(spec_rows, rem)
                except ValueError as exc:
                    raise ValueError(f"订单 {order.purchase_no}：{exc}") from exc
                if sum(qtys) != qty:
                    raise ValueError(
                        f"订单 {order.purchase_no}：各棉片数+尾数 {sum(qtys)} 与发货数 {qty} 不一致"
                    )
                boxes = len(qtys)
                pers = [int(s.get("qty_per_box") or 0) for s in spec_rows if int(s.get("qty") or 0) > 0]
                per = max(pers) if pers else 1
            else:
                if per < 1:
                    per = qty if boxes <= 1 else 1
                try:
                    expand_box_qtys(qty, max(boxes, 1), per)
                except ValueError as exc:
                    raise ValueError(f"订单 {order.purchase_no}：{exc}") from exc
        normalized.append((order, qty, max(boxes, 1), per, box_id_list, spec_rows, rem))

    slip_no = _next_shipment_no(db)
    first = normalized[0][0]
    slip = ShipmentSlip(
        slip_no=slip_no,
        customer_id=cid,
        customer_name=first.customer_name or cid,
        ship_date=ship_date,
        logistics=(logistics or "").strip() or None,
        remark=(remark or "").strip() or None,
        operator=(operator or "").strip() or None,
        line_count=0,
        total_qty=0,
        created_at=datetime.utcnow(),
    )
    db.add(slip)
    db.flush()

    shipments: list[Shipment] = []
    total_qty = 0
    for idx, (order, qty, boxes, per, box_id_list, spec_rows, rem) in enumerate(
        normalized, start=1
    ):
        ship = create_shipment(
            db,
            line_key=order.line_key,
            ship_date=ship_date,
            box_count=boxes,
            qty_per_box=per,
            qty=qty,
            logistics=logistics,
            remark=remark,
            operator=operator,
            slip_id=slip.id,
            shipment_no=f"{slip_no}-{idx:02d}",
            box_ids=box_id_list,
            pack_specs=spec_rows,
            remainder_qty=rem,
        )
        shipments.append(ship)
        total_qty += int(ship.qty or 0)

    slip.line_count = len(shipments)
    slip.total_qty = total_qty
    db.flush()
    append_scan_log(
        {
            "event": "ship_multi",
            "slip_no": slip.slip_no,
            "slip_id": slip.id,
            "customer_id": cid,
            "line_count": slip.line_count,
            "total_qty": total_qty,
            "operator": operator,
            "approval_status": SHIP_APPROVAL_PENDING,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return {
        "slip_id": slip.id,
        "slip_no": slip.slip_no,
        "customer_id": slip.customer_id,
        "customer_name": slip.customer_name or "",
        "ship_date": slip.ship_date,
        "logistics": slip.logistics or "",
        "remark": slip.remark or "",
        "operator": slip.operator or "",
        "line_count": slip.line_count,
        "total_qty": slip.total_qty,
        "shipment_ids": [s.id for s in shipments],
        "approval_status": SHIP_APPROVAL_PENDING,
        "message": "已提交发货，待 dxgc / dxgc002 / WGQ 确认后计入已发货",
    }


def get_latest_shipment(db: Session, line_key: str) -> Optional[Shipment]:
    key = (line_key or "").strip()
    if not key:
        return None
    return (
        db.query(Shipment)
        .filter(Shipment.line_key == key)
        .order_by(Shipment.id.desc())
        .first()
    )


def revoke_shipment(
    db: Session,
    *,
    shipment_id: Optional[int] = None,
    line_key: str = "",
    operator: str = "",
) -> dict:
    """撤销出库：将关联包装扫码改回 pending，并删除出库单。

    默认撤销该订单行最近一次出库；也可指定 shipment_id。
    """
    shipment: Optional[Shipment] = None
    if shipment_id:
        shipment = db.query(Shipment).filter(Shipment.id == int(shipment_id)).first()
        if not shipment:
            raise ValueError("发货单不存在")
    else:
        key = (line_key or "").strip()
        if not key:
            raise ValueError("请指定订单行或发货单")
        shipment = get_latest_shipment(db, key)
        if not shipment:
            raise ValueError("该订单没有可撤销的出库记录")

    scans = (
        db.query(OrderScan)
        .filter(OrderScan.shipment_id == shipment.id)
        .order_by(OrderScan.id.asc())
        .all()
    )
    restored = 0
    deleted_backfill = 0
    # 历史补录：删除合成条码，勿回 pending（避免假码占待发）
    # 待审核 awaiting / 已确认 shipped：普通扫码改回 pending
    for scan in scans:
        if is_backfill_scan(scan) or is_backfill_shipment(shipment):
            db.delete(scan)
            deleted_backfill += 1
        else:
            scan.status = SCAN_STATUS_PENDING
            scan.shipment_id = None
            scan.shipped_at = None
            restored += 1

    keep_box_ids: set[int] = set()
    for box in (
        db.query(ShipmentBox).filter(ShipmentBox.shipment_id == shipment.id).all()
    ):
        if (box.pack_mode or "") == "scan":
            keep_box_ids.add(box.id)
            box.shipment_id = None
            box.slip_id = None
            box.status = BOX_STATUS_SEALED
            box.ship_date = ""
        else:
            db.delete(box)
    for scan in scans:
        if is_backfill_scan(scan) or is_backfill_shipment(shipment):
            continue
        if scan.box_id and int(scan.box_id) not in keep_box_ids:
            scan.box_id = None

    info = {
        "id": shipment.id,
        "shipment_no": shipment.shipment_no,
        "line_key": shipment.line_key,
        "purchase_no": shipment.purchase_no,
        "qty": int(shipment.qty or 0),
        "restored_qty": restored,
        "deleted_backfill_qty": deleted_backfill,
        "ship_date": shipment.ship_date,
        "is_backfill": bool(deleted_backfill or is_backfill_shipment(shipment)),
    }
    append_scan_log(
        {
            "event": "ship_revoke",
            "shipment_no": shipment.shipment_no,
            "line_key": shipment.line_key,
            "purchase_no": shipment.purchase_no,
            "qty": info["qty"],
            "restored_qty": restored,
            "deleted_backfill_qty": deleted_backfill,
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    db.delete(shipment)
    db.flush()
    return info


def create_historical_ship_backfill(
    db: Session,
    *,
    line_key: str,
    ship_date: str,
    remark: str = "",
    operator: str = "",
    add_qty: Optional[int] = None,
    target_shipped_qty: Optional[int] = None,
) -> dict:
    """上线前历史发货补录：默认按「追加数量」计入累计已发（不进今日发）。

    - 优先 add_qty：在当前已发基础上再追加 N 片
    - 兼容 target_shipped_qty：把累计已发补到目标数
    - 不调用、不修改 register_scan
    """
    key = (line_key or "").strip()
    if not key:
        raise ValueError("请指定订单行")

    order = get_order_or_404(db, key)
    # 结案单允许历史补录（对齐交货），不影响扫码（结案本身已禁止扫码）

    qtys = compute_internal_ship_qtys(db, key, order=order)
    order_qty = int(round(float(qtys.get("order_qty") or 0)))
    current_shipped = int(qtys.get("shipped_qty") or 0)
    if order_qty <= 0:
        raise ValueError("订单数量无效，无法补录")

    add_n: int
    target: int
    if add_qty is not None:
        try:
            add_n = int(add_qty)
        except (TypeError, ValueError) as exc:
            raise ValueError("追加数量无效") from exc
        if add_n < 1:
            raise ValueError("追加数量须大于 0")
        target = current_shipped + add_n
        if target > order_qty:
            raise ValueError(
                f"追加 {add_n} 后累计已发 {target} 超过订单数 {order_qty}（当前已发 {current_shipped}）"
            )
    elif target_shipped_qty is not None:
        try:
            target = int(target_shipped_qty)
        except (TypeError, ValueError) as exc:
            raise ValueError("目标已发数量无效") from exc
        if target < 1:
            raise ValueError("目标已发数量须大于 0")
        if target > order_qty:
            raise ValueError(f"目标已发 {target} 不能超过订单数 {order_qty}")
        if target <= current_shipped:
            raise ValueError(
                f"当前已发已是 {current_shipped}，目标须大于当前已发（当前未发完 {qtys.get('unshipped_qty')}）"
            )
        add_n = target - current_shipped
    else:
        raise ValueError("请填写追加数量")

    op_name = (operator or "").strip() or "系统"
    ship_op = f"{BACKFILL_OPERATOR_PREFIX}{op_name}"[:64]
    extra = (remark or "").strip()
    ship_remark = f"{BACKFILL_REMARK_TAG}追加{add_n}·累计至{target}"
    if extra:
        ship_remark = f"{ship_remark}；{extra}"[:256]

    shipment = Shipment(
        shipment_no=_next_shipment_no(db),
        slip_id=None,
        line_key=key,
        purchase_no=order.purchase_no,
        customer_name=order.customer_name,
        product_goods_no=order.product_goods_no,
        product_goods_name=order.product_goods_name,
        qty=add_n,
        ship_date=(ship_date or "").strip() or datetime.now().strftime("%Y-%m-%d"),
        box_count=1,
        logistics=None,
        remark=ship_remark,
        operator=ship_op,
        approval_status=SHIP_APPROVAL_APPROVED,
        approved_by=op_name[:64],
        approved_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    db.add(shipment)
    db.flush()
    # 不写逐片合成条码，累计发按出库单 qty 计入；生产扫码路径不动

    after = compute_internal_ship_qtys(db, key, order=order)
    append_scan_log(
        {
            "event": "ship_backfill",
            "shipment_no": shipment.shipment_no,
            "line_key": key,
            "purchase_no": order.purchase_no,
            "added_qty": add_n,
            "target_shipped_qty": target,
            "shipped_after": after.get("shipped_qty"),
            "unshipped_after": after.get("unshipped_qty"),
            "operator": op_name,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return {
        "shipment_id": shipment.id,
        "shipment_no": shipment.shipment_no,
        "line_key": key,
        "purchase_no": order.purchase_no or "",
        "added_qty": add_n,
        "target_shipped_qty": target,
        "shipped_qty": int(after.get("shipped_qty") or 0),
        "pending_qty": int(after.get("pending_qty") or 0),
        "unshipped_qty": int(after.get("unshipped_qty") or 0),
        "order_qty": order_qty,
        "ship_date": shipment.ship_date,
        "message": (
            f"已追加历史发货 {add_n} 片：累计已发 {after.get('shipped_qty')}，"
            f"未发完 {after.get('unshipped_qty')}（不计入今日发）"
        ),
    }


def compute_internal_ship_qtys(
    db: Session,
    line_key: str,
    *,
    order: Optional[SrmOrder] = None,
) -> dict:
    """订单行内部发货口径（只读，不影响扫码）。

    订单数 / 已入库 / 待发货 / 待审核 / 已发货 / 未发完。
    已发货仅计确认后的 shipped；待审核 awaiting 不算已发。
    """
    key = (line_key or "").strip()
    if not order:
        order = db.query(SrmOrder).filter(SrmOrder.line_key == key).first()
    stats = get_scan_stats(db, [key]).get(key, {"pending": 0, "awaiting": 0, "shipped": 0})
    pending = int(stats.get("pending") or 0)
    awaiting = int(stats.get("awaiting") or 0)
    shipped = int(stats.get("shipped") or 0)
    inbound = pending + awaiting + shipped
    order_qty = float((order.batch_pur_qty if order else 0) or (order.output_qty if order else 0) or 0)
    unshipped = max(int(round(order_qty)) - shipped, 0) if order_qty else 0
    balanced = inbound == pending + awaiting + shipped
    if awaiting > 0:
        status = "awaiting_approve"
        status_label = "待审核"
    elif pending > 0:
        status = "pending_ship"
        status_label = "待发货"
    elif shipped > 0 and unshipped <= 0:
        status = "shipped_done"
        status_label = "已发完"
    elif shipped > 0:
        status = "partial"
        status_label = "部分已发"
    elif inbound <= 0:
        status = "await_pack"
        status_label = "待包装"
    else:
        status = "other"
        status_label = "—"
    return {
        "line_key": key,
        "order_qty": order_qty,
        "inbound_qty": inbound,
        "pending_qty": pending,
        "awaiting_qty": awaiting,
        "shipped_qty": shipped,
        "unshipped_qty": unshipped,
        "balanced": balanced,
        "can_close": bool(unshipped <= 0 and pending <= 0 and awaiting <= 0 and shipped > 0),
        "status": status,
        "status_label": status_label,
    }


def approve_shipments(
    db: Session,
    *,
    shipment_id: Optional[int] = None,
    slip_id: Optional[int] = None,
    approver: str = "",
) -> dict:
    """确认已发货：仅将 awaiting_approve → shipped，并标记出库单 approved。"""
    from system_auth import is_ship_approver_username

    who = (approver or "").strip()
    if not is_ship_approver_username(who):
        raise ValueError("仅 dxgc / dxgc002 / WGQ 可确认已发货")

    shipments: list[Shipment] = []
    if shipment_id:
        row = db.query(Shipment).filter(Shipment.id == int(shipment_id)).first()
        if not row:
            raise ValueError("发货单不存在")
        shipments = [row]
    elif slip_id:
        shipments = (
            db.query(Shipment)
            .filter(Shipment.slip_id == int(slip_id))
            .order_by(Shipment.id.asc())
            .all()
        )
        if not shipments:
            raise ValueError("合并送货单下没有出库明细")
    else:
        raise ValueError("请指定出库单或合并送货单")

    now = datetime.utcnow()
    approved_ids: list[int] = []
    total_qty = 0
    for ship in shipments:
        st = (ship.approval_status or SHIP_APPROVAL_APPROVED).strip()
        if st == SHIP_APPROVAL_APPROVED:
            continue
        scans = (
            db.query(OrderScan)
            .filter(OrderScan.shipment_id == ship.id)
            .order_by(OrderScan.id.asc())
            .all()
        )
        for scan in scans:
            if (scan.status or "") == SCAN_STATUS_AWAITING or is_backfill_scan(scan):
                scan.status = SCAN_STATUS_SHIPPED
                scan.shipped_at = now
            elif (scan.status or "") != SCAN_STATUS_SHIPPED:
                # 容错：挂在本单上的仍记为已发
                scan.status = SCAN_STATUS_SHIPPED
                scan.shipped_at = now
        ship.approval_status = SHIP_APPROVAL_APPROVED
        ship.approved_by = who[:64]
        ship.approved_at = now
        db.query(ShipmentBox).filter(ShipmentBox.shipment_id == ship.id).update(
            {ShipmentBox.status: BOX_STATUS_SHIPPED},
            synchronize_session=False,
        )
        approved_ids.append(ship.id)
        total_qty += int(ship.qty or 0)

    if not approved_ids:
        raise ValueError("没有待确认的出库单（可能已确认）")

    append_scan_log(
        {
            "event": "ship_approve",
            "shipment_ids": approved_ids,
            "slip_id": slip_id,
            "qty": total_qty,
            "approver": who,
            "at": now.isoformat(),
        }
    )
    return {
        "approved_count": len(approved_ids),
        "shipment_ids": approved_ids,
        "total_qty": total_qty,
        "approver": who,
        "message": f"已确认发货 {len(approved_ids)} 单，共 {total_qty} 片",
    }


def list_pending_ship_approvals(db: Session, *, limit: int = 200) -> list[dict]:
    """待审核出库单列表（成品发货页）。"""
    rows = (
        db.query(Shipment)
        .filter(Shipment.approval_status == SHIP_APPROVAL_PENDING)
        .order_by(Shipment.id.desc())
        .limit(max(1, min(int(limit or 200), 500)))
        .all()
    )
    ids = [int(s.id) for s in rows]
    box_qtys: dict[int, list[int]] = {}
    if ids:
        for b in (
            db.query(ShipmentBox)
            .filter(ShipmentBox.shipment_id.in_(ids))
            .order_by(ShipmentBox.box_index.asc(), ShipmentBox.id.asc())
            .all()
        ):
            box_qtys.setdefault(int(b.shipment_id), []).append(int(b.qty or 0))
    out: list[dict] = []
    for s in rows:
        qtys = box_qtys.get(int(s.id)) or []
        pack_note = format_pack_note_from_qtys(qtys)
        remark = pack_note or (s.remark or "").strip()
        out.append(
            {
                "id": s.id,
                "shipment_no": s.shipment_no,
                "slip_id": s.slip_id,
                "line_key": s.line_key,
                "purchase_no": s.purchase_no or "",
                "customer_name": s.customer_name or "",
                "product_goods_no": s.product_goods_no or "",
                "product_goods_name": s.product_goods_name or "",
                "qty": int(s.qty or 0),
                "ship_date": s.ship_date or "",
                "box_count": len(qtys) if qtys else int(s.box_count or 0),
                "qty_per_box": _typical_qty_per_box(qtys)
                if qtys
                else int(getattr(s, "qty_per_box", None) or 1),
                "operator": s.operator or "",
                "remark": remark,
                "pack_note": pack_note or remark,
                "approval_status": s.approval_status or SHIP_APPROVAL_PENDING,
                "created_at": s.created_at.isoformat(sep=" ", timespec="seconds")
                if s.created_at
                else None,
            }
        )
    return out


def shipped_qty_by_ship_date(
    db: Session,
    line_keys: list[str],
    *,
    ship_date: str,
) -> Dict[str, int]:
    """按送货日汇总已确认发货数量（approval_status=approved）。

    不含历史发货补录（backfill），补录只进累计已发，不进「今日发」。
    """
    from sqlalchemy import and_, not_, or_

    keys = [k for k in {(x or "").strip() for x in line_keys} if k]
    if not keys or not (ship_date or "").strip():
        return {}
    day = ship_date.strip()
    not_backfill = and_(
        or_(Shipment.operator.is_(None), ~Shipment.operator.like(f"{BACKFILL_OPERATOR_PREFIX}%")),
        or_(Shipment.remark.is_(None), ~Shipment.remark.like(f"{BACKFILL_REMARK_TAG}%")),
    )
    rows = (
        db.query(Shipment.line_key, func.coalesce(func.sum(Shipment.qty), 0))
        .filter(
            Shipment.line_key.in_(keys),
            Shipment.ship_date == day,
            Shipment.approval_status == SHIP_APPROVAL_APPROVED,
            not_backfill,
        )
        .group_by(Shipment.line_key)
        .all()
    )
    return {str(lk): int(qty or 0) for lk, qty in rows}


def list_shipments_for_line(db: Session, line_key: str, *, limit: int = 100) -> list[Shipment]:
    key = (line_key or "").strip()
    if not key:
        return []
    return (
        db.query(Shipment)
        .filter(Shipment.line_key == key)
        .order_by(Shipment.id.desc())
        .limit(max(1, min(int(limit or 100), 500)))
        .all()
    )


def get_line_reconcile(db: Session, line_key: str) -> dict:
    """内部对账：EMS 入库/发货闭合 + 历次出库单。SRM 数量仅只读旁注。"""
    order = get_order_or_404(db, line_key)
    qtys = compute_internal_ship_qtys(db, line_key, order=order)
    shipments = list_shipments_for_line(db, line_key)
    return {
        **qtys,
        "purchase_no": order.purchase_no or "",
        "customer_id": order.customer_id or "",
        "customer_name": order.customer_name or "",
        "model_code": order.product_goods_no or "",
        "model_name": order.product_goods_name or "",
        "product_spec": order.product_spec or "",
        "is_completed": bool(order.is_completed),
        # 客户侧只读，不参与对账结论
        "srm_delivery_qty": float(order.delivery_qty or 0),
        "srm_receive_qty": float(order.receive_qty or 0),
        "srm_un_delivery_qty": float(order.un_delivery_qty or 0),
        "shipments": [
            {
                "id": s.id,
                "shipment_no": s.shipment_no,
                "ship_date": s.ship_date,
                "qty": int(s.qty or 0),
                "box_count": int(s.box_count or 0),
                "qty_per_box": int(getattr(s, "qty_per_box", None) or 1),
                "logistics": s.logistics or "",
                "remark": s.remark or "",
                "operator": s.operator or "",
                "created_at": s.created_at.isoformat(sep=" ", timespec="seconds")
                if s.created_at
                else None,
            }
            for s in shipments
        ],
    }


def build_delivery_slip(db: Session, shipment_id: int) -> dict:
    """菲利斯风格送货单打印数据。

    若该出库单挂在合并送货单上，返回整张合并单；否则单行。
    交货数量=本次发货；未交数量=发后内部未发完。
    """
    shipment = db.query(Shipment).filter(Shipment.id == int(shipment_id)).first()
    if not shipment:
        raise ValueError("发货单不存在")
    if getattr(shipment, "slip_id", None):
        return build_delivery_slip_for_slip(db, int(shipment.slip_id))
    order = db.query(SrmOrder).filter(SrmOrder.line_key == shipment.line_key).first()
    qtys = compute_internal_ship_qtys(db, shipment.line_key, order=order)
    undelivered = int(qtys["unshipped_qty"])
    spec = ""
    unit = "PCS"
    if order:
        spec = (order.product_spec or order.product_goods_name or "").strip()
    goods_name = shipment.product_goods_name or (order.product_goods_name if order else "") or ""
    if not spec:
        spec = goods_name
    return {
        "id": shipment.id,
        "slip_id": None,
        "shipment_no": shipment.shipment_no,
        "ship_date": shipment.ship_date,
        "customer_name": shipment.customer_name
        or (order.customer_name if order else "")
        or "",
        "warehouse": "鼎雄成品仓",
        "logistics": shipment.logistics or "",
        "address": "",
        "operator": shipment.operator or "",
        "remark": shipment.remark or "",
        "box_count": int(shipment.box_count or 0),
        "print_title": "送货单",
        "company_name": COMPANY_NAME,
        "lines": [
            {
                "seq": 1,
                "purchase_no": shipment.purchase_no or "",
                "goods_no": shipment.product_goods_no
                or (order.product_goods_no if order else "")
                or "",
                "goods_name": goods_name,
                "spec": spec,
                "unit": unit,
                "order_qty": qtys["order_qty"],
                "delivery_qty": int(shipment.qty or 0),
                "undelivered_qty": undelivered,
                "remark": shipment.remark or "",
                "shipment_id": shipment.id,
            }
        ],
        "summary": qtys,
    }


def build_delivery_slip_for_slip(db: Session, slip_id: int) -> dict:
    """合并送货单打印：多订单多行。"""
    slip = db.query(ShipmentSlip).filter(ShipmentSlip.id == int(slip_id)).first()
    if not slip:
        raise ValueError("送货单不存在")
    shipments = (
        db.query(Shipment)
        .filter(Shipment.slip_id == slip.id)
        .order_by(Shipment.id.asc())
        .all()
    )
    if not shipments:
        raise ValueError("送货单无明细")
    lines = []
    for idx, shipment in enumerate(shipments, start=1):
        order = db.query(SrmOrder).filter(SrmOrder.line_key == shipment.line_key).first()
        qtys = compute_internal_ship_qtys(db, shipment.line_key, order=order)
        spec = ""
        if order:
            spec = (order.product_spec or order.product_goods_name or "").strip()
        goods_name = (
            shipment.product_goods_name
            or (order.product_goods_name if order else "")
            or ""
        )
        if not spec:
            spec = goods_name
        lines.append(
            {
                "seq": idx,
                "purchase_no": shipment.purchase_no or "",
                "goods_no": shipment.product_goods_no
                or (order.product_goods_no if order else "")
                or "",
                "goods_name": goods_name,
                "spec": spec,
                "unit": "PCS",
                "order_qty": qtys["order_qty"],
                "delivery_qty": int(shipment.qty or 0),
                "undelivered_qty": int(qtys["unshipped_qty"]),
                "remark": shipment.remark or slip.remark or "",
                "shipment_id": shipment.id,
            }
        )
    return {
        "id": shipments[0].id,
        "slip_id": slip.id,
        "shipment_no": slip.slip_no,
        "ship_date": slip.ship_date,
        "customer_name": slip.customer_name or "",
        "warehouse": "鼎雄成品仓",
        "logistics": slip.logistics or "",
        "address": "",
        "operator": slip.operator or "",
        "remark": slip.remark or "",
        "box_count": sum(int(s.box_count or 0) for s in shipments),
        "print_title": "送货单",
        "company_name": COMPANY_NAME,
        "lines": lines,
        "summary": {
            "line_count": len(lines),
            "total_qty": int(slip.total_qty or 0),
        },
    }


def _label_fields_for_shipment(db: Session, shipment: Shipment, *, slip_no: str) -> dict:
    order = db.query(SrmOrder).filter(SrmOrder.line_key == shipment.line_key).first()
    goods_no = (
        shipment.product_goods_no
        or (order.product_goods_no if order else "")
        or ""
    ).strip()
    goods_name = (
        shipment.product_goods_name
        or (order.product_goods_name if order else "")
        or ""
    ).strip()
    spec = ""
    if order:
        spec = (order.product_spec or "").strip()
    if not spec:
        spec = goods_name
    slip_text = (slip_no or shipment.shipment_no or "").strip()
    return {
        "title": "产品标签",
        "goods_no": goods_no,
        "goods_name": goods_name,
        "spec": spec,
        "version": "",
        "bom": "",
        "approval_no": "",
        "brand": "",
        "slip_no": slip_text,
        "supplier": COMPANY_NAME,
        "purchase_no": (shipment.purchase_no or "").strip(),
        "iqc": "",
        "ship_date": shipment.ship_date or "",
        "customer_name": shipment.customer_name or "",
        "barcode_text": goods_no,
        "slip_qr_text": slip_text,
        "qr_barcode_png": _qr_png_data_url(goods_no),
        "qr_slip_png": _qr_png_data_url(slip_text),
        "shipment_id": shipment.id,
        "shipment_no": shipment.shipment_no or "",
        "box_no": "",
        "box_index": 0,
        "box_count": int(shipment.box_count or 0),
        "qr_box_png": "",
        "box_qr_text": "",
    }


def _labels_from_shipments(
    db: Session,
    shipments: list[Shipment],
    *,
    slip_no: str,
) -> list[dict]:
    labels: list[dict] = []
    for shipment in shipments:
        ship_boxes = ensure_shipment_boxes(db, shipment)
        base = _label_fields_for_shipment(db, shipment, slip_no=slip_no)
        if not ship_boxes:
            labels.append({**base, "qty": int(shipment.qty or 0), "unit": "PCS"})
            continue
        for box in ship_boxes:
            url = box_trace_url(box.box_no)
            labels.append(
                {
                    **base,
                    "qty": int(box.qty or 0),
                    "unit": "PCS",
                    "box_no": box.box_no,
                    "box_index": int(box.box_index or 0),
                    "box_count": int(box.box_count or 0),
                    "qr_box_png": _qr_png_data_url(url),
                    "box_qr_text": url,
                    "barcode_text": box.box_no,
                    "qr_barcode_png": _qr_png_data_url(url),
                }
            )
    return labels


def build_product_label_for_box(db: Session, box_no: str) -> dict:
    no = (box_no or "").strip()
    box = db.query(ShipmentBox).filter(ShipmentBox.box_no == no).first()
    if not box:
        raise ValueError("箱号不存在")
    if getattr(box, "label_printed_at", None):
        raise ValueError("该箱二维码已打印，不能再打")
    order = db.query(SrmOrder).filter(SrmOrder.line_key == box.line_key).first()
    goods_no = (box.product_goods_no or (order.product_goods_no if order else "") or "").strip()
    goods_name = (
        box.product_goods_name or (order.product_goods_name if order else "") or ""
    ).strip()
    spec = (order.product_spec or "").strip() if order else ""
    if not spec:
        spec = goods_name
    slip_no = ""
    if box.slip_id:
        sl = db.query(ShipmentSlip).filter(ShipmentSlip.id == box.slip_id).first()
        slip_no = (sl.slip_no if sl else "") or ""
    if not slip_no and box.shipment_id:
        sh = db.query(Shipment).filter(Shipment.id == box.shipment_id).first()
        slip_no = (sh.shipment_no if sh else "") or ""
    url = box_trace_url(box.box_no)
    qr = _qr_png_data_url(url)
    label = {
        "title": "产品标签",
        "goods_no": goods_no,
        "goods_name": goods_name,
        "spec": spec,
        "version": "",
        "bom": "",
        "approval_no": "",
        "brand": "",
        "slip_no": slip_no,
        "supplier": COMPANY_NAME,
        "purchase_no": box.purchase_no or "",
        "iqc": "",
        "ship_date": box.ship_date or "",
        "customer_name": box.customer_name or "",
        "qty": int(box.qty or 0),
        "unit": "PCS",
        "box_no": box.box_no,
        "box_index": int(box.box_index or 0),
        "box_count": int(box.box_count or 0),
        "qr_box_png": qr,
        "box_qr_text": url,
        "barcode_text": box.box_no,
        "qr_barcode_png": qr,
        "qr_slip_png": _qr_png_data_url(slip_no or box.box_no),
        "slip_qr_text": slip_no or box.box_no,
        "shipment_id": box.shipment_id,
        "shipment_no": slip_no,
    }
    return {
        "slip_no": slip_no or box.box_no,
        "label_count": 1,
        "labels": [label],
        "already_printed": False,
    }


def mark_box_label_printed(db: Session, box_no: str, operator: str = "") -> dict:
    no = (box_no or "").strip()
    box = db.query(ShipmentBox).filter(ShipmentBox.box_no == no).first()
    if not box:
        raise ValueError("箱号不存在")
    if getattr(box, "label_printed_at", None):
        raise ValueError("该箱二维码已打印，不能再打")
    box.label_printed_at = datetime.utcnow()
    box.label_printed_by = (operator or "").strip() or None
    db.flush()
    append_scan_log(
        {
            "event": "box_label_print",
            "box_no": box.box_no,
            "operator": operator,
            "at": datetime.utcnow().isoformat(),
        }
    )
    return _box_payload(db, box)


def build_product_labels(
    db: Session,
    *,
    slip_id: Optional[int] = None,
    shipment_id: Optional[int] = None,
) -> dict:
    """产品标签打印数据：每箱一张，数量为本箱 PCS。"""
    slip = None
    shipments: list[Shipment] = []
    if slip_id:
        slip = db.query(ShipmentSlip).filter(ShipmentSlip.id == int(slip_id)).first()
        if not slip:
            raise ValueError("送货单不存在")
        shipments = (
            db.query(Shipment)
            .filter(Shipment.slip_id == slip.id)
            .order_by(Shipment.id.asc())
            .all()
        )
        if not shipments:
            raise ValueError("送货单无明细")
        slip_no = slip.slip_no or ""
    elif shipment_id:
        shipment = db.query(Shipment).filter(Shipment.id == int(shipment_id)).first()
        if not shipment:
            raise ValueError("发货单不存在")
        if getattr(shipment, "slip_id", None):
            return build_product_labels(db, slip_id=int(shipment.slip_id))
        shipments = [shipment]
        slip_no = shipment.shipment_no or ""
    else:
        raise ValueError("缺少送货单或发货单")
    labels = _labels_from_shipments(db, shipments, slip_no=slip_no)
    return {
        "slip_id": slip.id if slip else None,
        "shipment_id": None if slip else shipments[0].id,
        "slip_no": slip_no,
        "customer_name": (slip.customer_name if slip else shipments[0].customer_name) or "",
        "ship_date": (slip.ship_date if slip else shipments[0].ship_date) or "",
        "label_count": len(labels),
        "labels": labels,
    }


def list_pending_label_jobs(db: Session, *, limit: int = 200) -> dict:
    """待审核出库单按送货单分组，供 dxgc/dxgc002 打印产品标签。"""
    rows = (
        db.query(Shipment)
        .filter(Shipment.approval_status == SHIP_APPROVAL_PENDING)
        .order_by(Shipment.id.desc())
        .limit(max(1, min(int(limit or 200), 500)))
        .all()
    )
    slip_ids = sorted({int(s.slip_id) for s in rows if s.slip_id})
    slips = {}
    if slip_ids:
        for sl in db.query(ShipmentSlip).filter(ShipmentSlip.id.in_(slip_ids)).all():
            slips[sl.id] = sl

    grouped: dict[str, dict] = {}
    order_ids: list[str] = []
    for s in rows:
        if s.slip_id:
            key = f"slip-{s.slip_id}"
        else:
            key = f"ship-{s.id}"
        if key not in grouped:
            sl = slips.get(int(s.slip_id)) if s.slip_id else None
            grouped[key] = {
                "key": key,
                "slip_id": s.slip_id,
                "shipment_id": None if s.slip_id else s.id,
                "slip_no": (sl.slip_no if sl else s.shipment_no) or "",
                "customer_name": (sl.customer_name if sl else s.customer_name) or "",
                "ship_date": (sl.ship_date if sl else s.ship_date) or "",
                "operator": (sl.operator if sl else s.operator) or "",
                "line_count": 0,
                "total_qty": 0,
                "total_boxes": 0,
            }
            order_ids.append(key)
        g = grouped[key]
        g["line_count"] += 1
        g["total_qty"] += int(s.qty or 0)
        g["total_boxes"] += max(int(s.box_count or 0), 1)

    items = [grouped[k] for k in order_ids]
    return {
        "items": items,
        "slip_count": len(items),
        "label_count": sum(int(x["total_boxes"] or 0) for x in items),
        "total_qty": sum(int(x["total_qty"] or 0) for x in items),
    }


def build_pending_product_labels(db: Session, *, limit: int = 200) -> dict:
    jobs = list_pending_label_jobs(db, limit=limit)
    labels: list[dict] = []
    for job in jobs["items"]:
        try:
            if job.get("slip_id"):
                part = build_product_labels(db, slip_id=int(job["slip_id"]))
            else:
                part = build_product_labels(db, shipment_id=int(job["shipment_id"]))
        except ValueError:
            continue
        labels.extend(part.get("labels") or [])
    return {
        **jobs,
        "labels": labels,
        "label_count": len(labels),
    }


def _fmt_dt(v) -> Optional[str]:
    if not v:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat(sep=" ", timespec="seconds")
    return str(v)


def _scan_status_label(status: str) -> str:
    st = (status or "").strip()
    if st == SCAN_STATUS_PENDING:
        return "待发"
    if st == SCAN_STATUS_AWAITING:
        return "待审核"
    if st == SCAN_STATUS_SHIPPED:
        return "已出库"
    return st or "—"


def _shipment_status_label(shipment: Optional[Shipment]) -> str:
    if not shipment:
        return "—"
    st = (shipment.approval_status or SHIP_APPROVAL_APPROVED).strip()
    if st == SHIP_APPROVAL_PENDING:
        return "待审核"
    return "已出库"


def _shipment_record_row(db: Session, shipment: Shipment) -> dict:
    slip = None
    if getattr(shipment, "slip_id", None):
        slip = (
            db.query(ShipmentSlip)
            .filter(ShipmentSlip.id == int(shipment.slip_id))
            .first()
        )
    return {
        "id": int(shipment.id),
        "shipment_no": shipment.shipment_no or "",
        "slip_id": getattr(shipment, "slip_id", None),
        "slip_no": (slip.slip_no if slip else "") or "",
        "line_key": shipment.line_key or "",
        "purchase_no": shipment.purchase_no or "",
        "customer_name": shipment.customer_name or "",
        "product_goods_no": shipment.product_goods_no or "",
        "product_goods_name": shipment.product_goods_name or "",
        "qty": int(shipment.qty or 0),
        "ship_date": shipment.ship_date or "",
        "box_count": int(shipment.box_count or 0),
        "qty_per_box": int(getattr(shipment, "qty_per_box", None) or 1),
        "logistics": shipment.logistics or "",
        "remark": shipment.remark or "",
        "operator": shipment.operator or "",
        "approval_status": (shipment.approval_status or SHIP_APPROVAL_APPROVED).strip(),
        "status_label": _shipment_status_label(shipment),
        "approved_by": getattr(shipment, "approved_by", None) or "",
        "approved_at": _fmt_dt(getattr(shipment, "approved_at", None)),
        "created_at": _fmt_dt(shipment.created_at),
    }


def list_shipment_records(
    db: Session,
    *,
    keyword: str = "",
    status: str = "",
    limit: int = 200,
) -> dict:
    """出库批次列表（只读）。keyword 可搜 SH-/订单/品号/板码。"""
    kw = (keyword or "").strip()
    st = (status or "").strip().lower()
    highlight_id: Optional[int] = None
    barcode_hint = ""
    matched_barcode = ""
    matched_shipment_no = ""

    q = db.query(Shipment)
    if st == "pending":
        q = q.filter(Shipment.approval_status == SHIP_APPROVAL_PENDING)
    elif st in ("approved", "shipped"):
        q = q.filter(Shipment.approval_status == SHIP_APPROVAL_APPROVED)

    if kw:
        up = kw.upper()
        if up.startswith("SH-"):
            q = q.filter(Shipment.shipment_no.like(f"%{kw}%"))
            matched_shipment_no = kw
        else:
            scan = _find_scan_by_barcode(db, kw)
            if scan and scan.shipment_id:
                highlight_id = int(scan.shipment_id)
                matched_barcode = scan.barcode or kw
                shipment = (
                    db.query(Shipment)
                    .filter(Shipment.id == int(scan.shipment_id))
                    .first()
                )
                if shipment:
                    matched_shipment_no = shipment.shipment_no or ""
                    barcode_hint = (
                        f"板码 {matched_barcode} 在批次 {matched_shipment_no}（共 {int(shipment.qty or 0)} 片）"
                    )
                q = q.filter(Shipment.id == int(scan.shipment_id))
            elif scan:
                matched_barcode = scan.barcode or kw
                barcode_hint = f"板码 {matched_barcode} 已入库待发，尚未出库"
                return {
                    "items": [],
                    "highlight_id": None,
                    "barcode_hint": barcode_hint,
                    "matched_barcode": matched_barcode,
                    "matched_shipment_no": "",
                }
            else:
                like = f"%{kw}%"
                q = q.filter(
                    or_(
                        Shipment.purchase_no.like(like),
                        Shipment.product_goods_no.like(like),
                        Shipment.product_goods_name.like(like),
                        Shipment.customer_name.like(like),
                        Shipment.shipment_no.like(like),
                    )
                )

    rows = q.order_by(Shipment.id.desc()).limit(max(1, min(int(limit or 200), 500))).all()
    return {
        "items": [_shipment_record_row(db, s) for s in rows],
        "highlight_id": highlight_id,
        "barcode_hint": barcode_hint,
        "matched_barcode": matched_barcode,
        "matched_shipment_no": matched_shipment_no,
    }


def lookup_shipment_record(db: Session, raw: str) -> dict:
    """扫/输入板码或 SH 批次号，返回所属批次及同批板码（只读）。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("请提供板码或批次号")

    shipment: Optional[Shipment] = None
    scan: Optional[OrderScan] = None
    lookup_type = "barcode"

    up = text.upper()
    if up.startswith("SH-"):
        lookup_type = "shipment_no"
        shipment = (
            db.query(Shipment)
            .filter(Shipment.shipment_no == text)
            .first()
        )
        if not shipment:
            shipment = (
                db.query(Shipment)
                .filter(Shipment.shipment_no.like(f"%{text}%"))
                .order_by(Shipment.id.desc())
                .first()
            )
        if not shipment:
            raise ValueError(f"未找到批次 {text}")
    else:
        scan = _find_scan_by_barcode(db, text)
        if not scan:
            raise ValueError("未找到该入库编码")
        if scan.shipment_id:
            shipment = (
                db.query(Shipment)
                .filter(Shipment.id == int(scan.shipment_id))
                .first()
            )

    scan_payload = None
    if scan:
        order = db.query(SrmOrder).filter(SrmOrder.line_key == scan.line_key).first()
        scan_payload = {
            "barcode": scan.barcode or text,
            "status": scan.status or "",
            "status_label": _scan_status_label(scan.status or ""),
            "line_key": scan.line_key or "",
            "purchase_no": scan.purchase_no or (order.purchase_no if order else "") or "",
            "product_goods_no": (order.product_goods_no if order else "") or "",
            "product_goods_name": (order.product_goods_name if order else "") or "",
            "customer_name": (order.customer_name if order else "") or "",
            "operator": scan.operator or "",
            "scanned_at": _fmt_dt(scan.scanned_at),
            "shipped_at": _fmt_dt(scan.shipped_at),
            "shipment_id": scan.shipment_id,
        }

    if not shipment:
        return {
            "lookup_type": lookup_type,
            "found": True,
            "scan": scan_payload,
            "shipment": None,
            "batch_barcodes": [],
            "batch_total": 0,
            "message": f"板码 {scan.barcode if scan else text} 已入库，尚未出库",
        }

    batch_scans = (
        db.query(OrderScan)
        .filter(OrderScan.shipment_id == int(shipment.id))
        .order_by(OrderScan.id.asc())
        .all()
    )
    if not scan_payload and batch_scans:
        first = batch_scans[0]
        order = db.query(SrmOrder).filter(SrmOrder.line_key == first.line_key).first()
        scan_payload = {
            "barcode": "",
            "status": first.status or "",
            "status_label": _scan_status_label(first.status or ""),
            "line_key": first.line_key or "",
            "purchase_no": first.purchase_no or (order.purchase_no if order else "") or "",
            "product_goods_no": (order.product_goods_no if order else "") or "",
            "product_goods_name": (order.product_goods_name if order else "") or "",
            "customer_name": (order.customer_name if order else "") or "",
            "operator": "",
            "scanned_at": None,
            "shipped_at": None,
            "shipment_id": shipment.id,
        }

    return {
        "lookup_type": lookup_type,
        "found": True,
        "scan": scan_payload,
        "shipment": _shipment_record_row(db, shipment),
        "batch_barcodes": [
            {
                "barcode": s.barcode,
                "operator": s.operator or "",
                "scanned_at": _fmt_dt(s.scanned_at),
                "shipped_at": _fmt_dt(s.shipped_at),
                "status": s.status or "",
                "status_label": _scan_status_label(s.status or ""),
            }
            for s in batch_scans
        ],
        "batch_total": len(batch_scans),
        "message": "",
    }


def get_shipment_record_barcodes(
    db: Session,
    shipment_id: int,
    *,
    limit: int = 20000,
) -> dict:
    shipment = db.query(Shipment).filter(Shipment.id == int(shipment_id)).first()
    if not shipment:
        raise ValueError("出库批次不存在")
    q = db.query(OrderScan).filter(OrderScan.shipment_id == int(shipment_id))
    total = q.count()
    rows = q.order_by(OrderScan.id.asc()).limit(max(1, min(int(limit or 20000), 20000))).all()
    return {
        "shipment": _shipment_record_row(db, shipment),
        "total": int(total),
        "items": [
            {
                "barcode": s.barcode,
                "operator": s.operator or "",
                "scanned_at": _fmt_dt(s.scanned_at),
                "shipped_at": _fmt_dt(s.shipped_at),
                "status": s.status or "",
                "status_label": _scan_status_label(s.status or ""),
            }
            for s in rows
        ],
    }


def get_box_trace(db: Session, box_no: str) -> dict:
    no = (box_no or "").strip()
    if not no:
        raise ValueError("请提供箱号")
    box = db.query(ShipmentBox).filter(ShipmentBox.box_no == no).first()
    if not box:
        raise ValueError("箱号不存在")
    shipment = db.query(Shipment).filter(Shipment.id == box.shipment_id).first()
    slip = None
    if box.slip_id:
        slip = db.query(ShipmentSlip).filter(ShipmentSlip.id == box.slip_id).first()
    scans = (
        db.query(OrderScan)
        .filter(OrderScan.box_id == box.id)
        .order_by(OrderScan.id.asc())
        .all()
    )
    status = (shipment.approval_status if shipment else "") or ""
    if status == SHIP_APPROVAL_PENDING:
        status_label = "待审核"
    elif status == SHIP_APPROVAL_APPROVED:
        status_label = "已发货"
    else:
        status_label = status or "—"
    return {
        "box_no": box.box_no,
        "box_index": int(box.box_index or 0),
        "box_count": int(box.box_count or 0),
        "qty": int(box.qty or 0),
        "barcode_count": len(scans),
        "ship_date": box.ship_date or (shipment.ship_date if shipment else "") or "",
        "purchase_no": box.purchase_no or "",
        "goods_no": box.product_goods_no or "",
        "goods_name": box.product_goods_name or "",
        "customer_name": box.customer_name or "",
        "slip_no": (slip.slip_no if slip else None)
        or (shipment.shipment_no if shipment else "")
        or "",
        "shipment_no": (shipment.shipment_no if shipment else "") or "",
        "operator": (shipment.operator if shipment else "") or "",
        "approval_status": status,
        "status_label": status_label,
        "approved_at": _fmt_dt(getattr(shipment, "approved_at", None) if shipment else None),
        "created_at": _fmt_dt(box.created_at),
        "barcodes": [
            {
                "barcode": s.barcode,
                "scanned_at": _fmt_dt(s.scanned_at),
                "operator": s.operator or "",
                "status": s.status,
            }
            for s in scans
        ],
    }


def get_box_trace_by_barcode(db: Session, barcode: str) -> dict:
    code = (barcode or "").strip()
    if not code:
        raise ValueError("请提供板码")
    scan = _find_scan_by_barcode(db, code)
    if not scan:
        raise ValueError("未找到该入库编码")
    if not scan.box_id:
        raise ValueError("该编码已入库，但尚未装入发货箱")
    box = db.query(ShipmentBox).filter(ShipmentBox.id == scan.box_id).first()
    if not box:
        raise ValueError("该编码已入库，但尚未装入发货箱")
    data = get_box_trace(db, box.box_no)
    data["matched_barcode"] = scan.barcode or code
    return data
