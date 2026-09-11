import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from config import get_enabled_customers
from models import SrmOrder, SrmReconciliation, SyncLog
from customer_kitting import save_synced_order
from engineering_service import refresh_customer_material_kitting
from kingdee_client import KingdeeScpClient
from order_retention import is_within_retention, parse_order_date, retention_cutoff_date, retention_cutoff_str
from receive_events import sync_receive_events
from receive_snapshot import snapshot_receive_qty
from srm_client import SrmClient, _normalize_seq, is_line_completed, make_line_key
from srm_client_v2 import SrmClientV2

logger = logging.getLogger(__name__)


def get_srm_client(customer: dict):
    api_type = customer.get("api_type")
    if api_type == "v2":
        return SrmClientV2(customer)
    if api_type == "kingdee":
        return KingdeeScpClient(customer)
    return SrmClient(customer)


def _apply_customer_meta(order_data: dict, customer: dict) -> dict:
    order_data["customer_name"] = customer.get("name") or customer["id"]
    return order_data


def _build_order_from_line_v1(customer: dict, wo: dict, line: dict, head: dict) -> dict:
    purchase_no = (line.get("purchaseNo") or wo.get("purchaseNo") or "").strip()
    seq = str(line.get("purchaseSeq") or "0")
    phase = str(line.get("purchasePhaseSeq") or "0")
    return {
        "line_key": make_line_key(customer["id"], purchase_no, seq, phase),
        "customer_id": customer["id"],
        "customer_name": customer.get("name") or customer["id"],
        "purchase_no": purchase_no,
        "purchase_seq": seq,
        "purchase_phase_seq": phase,
        "workorder_no": wo.get("workorderNo"),
        "product_goods_no": line.get("goodsNo") or wo.get("productGoodsNo"),
        "product_goods_name": line.get("goodsName") or wo.get("productGoodsName"),
        "product_spec": line.get("spec") or wo.get("productSpec"),
        "batch_pur_qty": float(line.get("batchPurQty") or wo.get("outputQty") or 0),
        "delivery_qty": float(line.get("deliveryQty") or 0),
        "receive_qty": float(line.get("receiveQty") or 0),
        "un_delivery_qty": float(line.get("unDeliveryQty") or 0),
        "un_receive_qty": float(line.get("unReceiveQty") or 0),
        "output_qty": float(wo.get("outputQty") or line.get("batchPurQty") or 0),
        "collected_sets_qty": float(wo.get("collectedSetsQty") or 0),
        "doc_date": wo.get("docDate"),
        "purchase_date": line.get("purchaseDate")
        or (head.get("purchaseDate") if head else None)
        or line.get("purchaseDate")
        or wo.get("docDate"),
        "expect_arrival_date": line.get("expectArrivalDate"),
        "order_type_name": line.get("orderTypeName")
        or (head.get("orderTypeName") if head else None)
        or "委外订单",
        "tax_amount": float(line.get("taxAmount") or 0),
        "no_tax_amount": float(line.get("noTaxAmount") or 0),
        "sum_tax_amount": float(head.get("sumTaxAmount") or line.get("taxAmount") or 0)
        if head
        else float(line.get("taxAmount") or 0),
        "sum_no_tax_amount": float(head.get("sumNoTaxAmount") or line.get("noTaxAmount") or 0)
        if head
        else float(line.get("noTaxAmount") or 0),
        "srm_status": str(line.get("status") or ""),
        "srm_status_name": line.get("statusName") or "",
        "is_completed": is_line_completed(line),
        "data_source": "订单跟踪",
        "synced_at": datetime.utcnow(),
    }


def _build_order_from_asn_pur_line(customer: dict, line: dict) -> dict:
    """ASN 跟踪 → 新增 ASN → 订单性质「委外订单」明细行。"""
    purchase_no = str(line.get("purchaseNo") or "").strip()
    # 历史订单跟踪接口常用 0001，与 ASN 的 1 对齐以便续更同一 line_key
    seq = _normalize_seq(line.get("purchaseSeq"), width=4)
    phase = _normalize_seq(line.get("purchasePhaseSeq"))
    qty = float(line.get("batchPurQty") or 0)
    status_name = (line.get("statusName") or line.get("purStatus") or "").strip()
    return {
        "line_key": make_line_key(customer["id"], purchase_no, seq, phase),
        "customer_id": customer["id"],
        "customer_name": customer.get("name") or customer["id"],
        "purchase_no": purchase_no,
        "purchase_seq": seq,
        "purchase_phase_seq": phase,
        "workorder_no": line.get("workorderNo") or line.get("docNo"),
        "product_goods_no": line.get("goodsNo"),
        "product_goods_name": line.get("goodsName"),
        "product_spec": line.get("spec") or line.get("itemFeatureName"),
        "batch_pur_qty": qty,
        "delivery_qty": float(line.get("deliveryQty") or 0),
        "receive_qty": float(line.get("receiveQty") or 0),
        "un_delivery_qty": float(line.get("unDeliveryQty") or 0),
        "un_receive_qty": float(line.get("unReceiveQty") or 0),
        "output_qty": qty,
        "collected_sets_qty": float(line.get("collectedSetsQty") or 0),
        "doc_date": line.get("purchaseDate") or line.get("docDate"),
        "purchase_date": line.get("purchaseDate") or line.get("docDate"),
        "expect_arrival_date": line.get("expectArrivalDate") or line.get("deliveryDate"),
        "order_type_name": line.get("orderTypeName") or "委外订单",
        "tax_amount": float(line.get("taxAmount") or 0),
        "no_tax_amount": float(line.get("noTaxAmount") or 0),
        "sum_tax_amount": float(line.get("taxAmount") or 0),
        "sum_no_tax_amount": float(line.get("noTaxAmount") or 0),
        "srm_status": str(line.get("status") or ""),
        "srm_status_name": status_name,
        "is_completed": is_line_completed(
            {
                "statusName": status_name,
                "unDeliveryQty": line.get("unDeliveryQty"),
                "unReceiveQty": line.get("unReceiveQty"),
                "batchPurQty": qty,
            }
        ),
        "data_source": "ASN跟踪(委外订单)",
        "synced_at": datetime.utcnow(),
    }


def _find_existing_order(db: Session, customer_id: str, order_data: dict) -> Optional[SrmOrder]:
    key = order_data["line_key"]
    existing = db.query(SrmOrder).filter(SrmOrder.line_key == key).first()
    if existing:
        return existing
    # 兼容未补零的旧 line_key
    purchase_no = order_data["purchase_no"]
    seq_raw = _normalize_seq(order_data.get("purchase_seq"))
    phase = _normalize_seq(order_data.get("purchase_phase_seq"))
    alt_keys = {
        make_line_key(customer_id, purchase_no, seq_raw, phase),
        make_line_key(customer_id, purchase_no, seq_raw.zfill(4) if seq_raw.isdigit() else seq_raw, phase),
    }
    alt_keys.discard(key)
    if not alt_keys:
        return None
    return (
        db.query(SrmOrder)
        .filter(SrmOrder.customer_id == customer_id, SrmOrder.line_key.in_(alt_keys))
        .first()
    )


def _build_order_from_workorder_v1(
    customer: dict, wo: dict, head: dict, status_info: dict = None
) -> dict:
    purchase_no = (wo.get("purchaseNo") or "").strip()
    qty = float(wo.get("outputQty") or 0)
    status_name = (status_info or {}).get("statusName") or ""
    completed = not status_info or _resolve_completion(status_info)
    if not status_name:
        status_name = "已结案" if completed else "无跟踪明细"
    return {
        "line_key": make_line_key(customer["id"], purchase_no, "0", "0"),
        "customer_id": customer["id"],
        "customer_name": customer.get("name") or customer["id"],
        "purchase_no": purchase_no,
        "purchase_seq": "0",
        "purchase_phase_seq": "0",
        "workorder_no": wo.get("workorderNo"),
        "product_goods_no": wo.get("productGoodsNo"),
        "product_goods_name": wo.get("productGoodsName"),
        "product_spec": wo.get("productSpec"),
        "batch_pur_qty": qty,
        "delivery_qty": 0,
        "receive_qty": 0,
        "un_delivery_qty": 0 if completed else qty,
        "un_receive_qty": 0 if completed else qty,
        "output_qty": qty,
        "collected_sets_qty": float(wo.get("collectedSetsQty") or 0),
        "doc_date": wo.get("docDate"),
        "purchase_date": (head.get("purchaseDate") if head else None) or wo.get("docDate"),
        "expect_arrival_date": None,
        "order_type_name": (head.get("orderTypeName") if head else None) or "委外订单",
        "tax_amount": float(head.get("sumTaxAmount") or 0) if head else 0,
        "no_tax_amount": float(head.get("sumNoTaxAmount") or 0) if head else 0,
        "sum_tax_amount": float(head.get("sumTaxAmount") or 0) if head else 0,
        "sum_no_tax_amount": float(head.get("sumNoTaxAmount") or 0) if head else 0,
        "srm_status": str((status_info or {}).get("status") or ""),
        "srm_status_name": status_name,
        "is_completed": completed,
        "data_source": "委外发料(无明细)",
        "synced_at": datetime.utcnow(),
    }


def _build_order_from_line_kingdee(customer: dict, line: dict) -> dict:
    purchase_no = str(_pick(line, "FBillNo", "purchaseNo") or "").strip()
    product_goods_no = str(
        _pick(line, "FMaterialId.FNumber", "itemNo", "goodsNo") or ""
    ).strip()
    # 永联金蝶列表分录号不稳定（IDENTITY 行号 / ENTRY 常空），统一用料号做 seq，避免多行撞 line_key
    seq = product_goods_no or str(
        _pick(line, "FPOOrderEntry_FENTRYID", "FSeq", "FIDENTITYID", "purchaseSeq") or "0"
    ).strip() or "0"
    phase = str(_pick(line, "purchasePhaseSeq") or "0")
    purchase_qty = float(_pick(line, "FQty", "purchaseQty", default=0) or 0)
    receive_qty = float(_pick(line, "FReceiveQty", "receiveQty", default=0) or 0)
    remain_qty = float(_pick(line, "FRemainReceiveQty", "unReceiveQty", default=0) or 0)
    if remain_qty <= 0 and purchase_qty > receive_qty:
        remain_qty = max(purchase_qty - receive_qty, 0)
    status_code = str(_pick(line, "FDocumentStatus", "status") or "").strip()
    status_name = {"C": "已审核", "B": "审核中", "A": "创建", "D": "重新审核"}.get(status_code, status_code or "进行中")
    close_status = str(_pick(line, "FMRPCloseStatus", "FCloseStatus") or "").strip()
    if close_status in ("关闭", "B", "Y") or line.get("_pur_closed"):
        status_name = "行业业务关闭"
        is_completed = True
    else:
        is_completed = False
    tax_price = float(_pick(line, "FTaxPrice", "taxPrice", default=0) or 0)
    tax_amount = float(_pick(line, "FAllAmount", "taxAmount", default=0) or 0)
    if tax_amount <= 0 and tax_price > 0 and purchase_qty > 0:
        tax_amount = tax_price * purchase_qty
    # 已有收货优先；PUR 结案行会带 FReceiveQty=采购量
    if is_completed and receive_qty <= 0 and purchase_qty > 0:
        receive_qty = purchase_qty
        remain_qty = 0.0
    return {
        "line_key": make_line_key(customer["id"], purchase_no, seq, phase),
        "customer_id": customer["id"],
        "customer_name": customer.get("name") or customer["id"],
        "purchase_no": purchase_no,
        "purchase_seq": seq,
        "purchase_phase_seq": phase,
        "workorder_no": None,
        "product_goods_no": product_goods_no or None,
        "product_goods_name": _pick(line, "FMaterialName", "FMaterialId.FName", "itemName", "goodsName"),
        "product_spec": _pick(line, "FMaterialId.FSpecification", "itemSpec", "spec"),
        "batch_pur_qty": purchase_qty,
        "delivery_qty": max(purchase_qty - remain_qty, receive_qty),
        "receive_qty": receive_qty,
        "un_delivery_qty": remain_qty,
        "un_receive_qty": remain_qty,
        "output_qty": purchase_qty,
        "collected_sets_qty": 0,
        "doc_date": _pick(line, "FDate", "purchaseDate"),
        "purchase_date": _pick(line, "FDate", "purchaseDate"),
        "expect_arrival_date": _pick(line, "FDeliveryDate", "expectArrivalDate"),
        "order_type_name": "采购订单",
        "tax_price": tax_price,
        "tax_amount": tax_amount,
        "no_tax_amount": tax_amount,
        "sum_tax_amount": tax_amount,
        "sum_no_tax_amount": tax_amount,
        "srm_status": status_code,
        "srm_status_name": status_name,
        "is_completed": is_completed,
        "data_source": "金蝶SCP采购订单",
        "synced_at": datetime.utcnow(),
    }


def _pick(data: dict, *keys, default=None):
    for key in keys:
        if key in data and data[key] is not None and data[key] != "":
            return data[key]
    return default


def _v2_line_phase(line: dict) -> str:
    line_seq = _pick(line, "purchaseLineSeq", "purchase_phase_seq")
    batch_seq = _pick(line, "purchaseBatchSeq")
    if line_seq is not None and batch_seq is not None:
        return f"{line_seq}-{batch_seq}"
    return str(_pick(line, "purchasePhaseSeq", "purchase_phase_seq", "phaseSeq") or "0")


def _build_order_from_line_v2(customer: dict, head: dict, line: dict, closed: bool = False) -> dict:
    purchase_no = str(_pick(line, "purchaseNo", "purchase_no") or _pick(head, "purchaseNo", "purchase_no") or "").strip()
    seq = str(_pick(line, "purchaseSeq", "purchase_seq", "lineNo", "seq") or "0")
    phase = _v2_line_phase(line)
    purchase_qty = float(_pick(line, "purchaseQty", "batchPurQty", "batch_pur_qty", "qty", default=0) or 0)
    delivery_qty = float(_pick(line, "deliveryQty", "delivery_qty", default=0) or 0)
    receive_qty = float(_pick(line, "receivedQty", "receiptQty", "receiveQty", "receive_qty", default=0) or 0)
    unpaid_qty = float(_pick(line, "unpaidQty", "un_receive_qty", "unReceiveQty", default=0) or 0)
    if not closed and unpaid_qty <= 0 and purchase_qty > receive_qty:
        unpaid_qty = max(purchase_qty - receive_qty, 0)
    if closed:
        unpaid_qty = 0
        status_name = _pick(line, "caseCloseDesc", "statusName") or "已结案"
        is_completed = True
        data_source = "订单跟踪(已结案)"
    else:
        status_name = _pick(line, "statusName", "status_name", "purchaseTypeDesc") or ""
        if unpaid_qty > 0:
            status_name = status_name or "未交完"
        elif not status_name:
            status_name = "进行中"
        line_for_status = {
            "statusName": status_name,
            "status": _pick(line, "status", default=""),
            "unDeliveryQty": max(purchase_qty - delivery_qty, 0),
            "unReceiveQty": unpaid_qty,
            "batchPurQty": purchase_qty,
        }
        is_completed = is_line_completed(line_for_status)
        data_source = "订单跟踪(未结案)"
    return {
        "line_key": make_line_key(customer["id"], purchase_no, seq, phase),
        "customer_id": customer["id"],
        "customer_name": customer.get("name") or customer["id"],
        "purchase_no": purchase_no,
        "purchase_seq": seq,
        "purchase_phase_seq": phase,
        "workorder_no": _pick(line, "workorderNo", "workorder_no"),
        "product_goods_no": _pick(line, "itemNo", "goodsNo", "goods_no", "productGoodsNo", "materialNo"),
        "product_goods_name": _pick(line, "itemName", "goodsName", "goods_name", "productGoodsName", "materialName"),
        "product_spec": _pick(line, "itemSpec", "spec", "productSpec", "goodsSpec"),
        "batch_pur_qty": purchase_qty,
        "delivery_qty": delivery_qty,
        "receive_qty": receive_qty,
        "un_delivery_qty": 0 if closed else max(purchase_qty - delivery_qty, 0),
        "un_receive_qty": unpaid_qty,
        "output_qty": purchase_qty,
        "collected_sets_qty": 0,
        "doc_date": _pick(line, "purchaseDate", "purchase_date") or _pick(head, "purchaseDate", "purchase_date"),
        "purchase_date": _pick(line, "purchaseDate", "purchase_date") or _pick(head, "purchaseDate", "purchase_date"),
        "expect_arrival_date": _pick(line, "arrivalDate", "expectArrivalDate", "expect_arrival_date", "purchaseAgreementDate"),
        "order_type_name": _pick(line, "purchaseTypeDesc", "order_type_name", "purchaseTypeName") or _pick(head, "purchaseTypeDesc") or "采购订单",
        "tax_amount": float(_pick(line, "transCurrTaxAmount", "taxAmount", "tax_amount", default=0) or 0),
        "no_tax_amount": float(_pick(line, "transCurrNotTaxAmount", "noTaxAmount", "no_tax_amount", default=0) or 0),
        "sum_tax_amount": float(_pick(line, "transCurrTaxAmount", "taxAmount", default=0) or 0),
        "sum_no_tax_amount": float(_pick(line, "transCurrNotTaxAmount", "noTaxAmount", default=0) or 0),
        "srm_status": str(_pick(line, "status", "purchaseStatus", default="") or ""),
        "srm_status_name": status_name,
        "is_completed": is_completed,
        "data_source": data_source,
        "synced_at": datetime.utcnow(),
    }


def _build_order_from_head_v2(customer: dict, head: dict) -> dict:
    purchase_no = str(_pick(head, "purchaseNo", "purchase_no") or "").strip()
    qty = float(_pick(head, "batchPurQty", "purchaseQty", "qty", "totalQty", default=0) or 0)
    status_name = _pick(head, "statusName", "status_name", "purchaseStatusName") or "无行明细"
    return {
        "line_key": make_line_key(customer["id"], purchase_no, "0", "0"),
        "customer_id": customer["id"],
        "customer_name": customer.get("name") or customer["id"],
        "purchase_no": purchase_no,
        "purchase_seq": "0",
        "purchase_phase_seq": "0",
        "workorder_no": _pick(head, "workorderNo", "workorder_no"),
        "product_goods_no": _pick(head, "goodsNo", "productGoodsNo", "materialNo"),
        "product_goods_name": _pick(head, "goodsName", "productGoodsName", "materialName"),
        "product_spec": _pick(head, "spec", "productSpec"),
        "batch_pur_qty": qty,
        "delivery_qty": float(_pick(head, "deliveryQty", default=0) or 0),
        "receive_qty": float(_pick(head, "receiveQty", default=0) or 0),
        "un_delivery_qty": float(_pick(head, "unDeliveryQty", default=0) or 0),
        "un_receive_qty": float(_pick(head, "unReceiveQty", default=0) or 0),
        "output_qty": qty,
        "collected_sets_qty": 0,
        "doc_date": _pick(head, "purchaseDate", "purchase_date", "docDate"),
        "purchase_date": _pick(head, "purchaseDate", "purchase_date", "docDate"),
        "expect_arrival_date": _pick(head, "expectArrivalDate", "deliveryDate"),
        "order_type_name": _pick(head, "orderTypeName", "purchaseTypeName") or "采购订单",
        "tax_amount": float(_pick(head, "taxAmount", "sumTaxAmount", default=0) or 0),
        "no_tax_amount": float(_pick(head, "noTaxAmount", "sumNoTaxAmount", default=0) or 0),
        "sum_tax_amount": float(_pick(head, "sumTaxAmount", "taxAmount", default=0) or 0),
        "sum_no_tax_amount": float(_pick(head, "sumNoTaxAmount", "noTaxAmount", default=0) or 0),
        "srm_status": str(_pick(head, "status", "purchaseStatus", default="") or ""),
        "srm_status_name": status_name,
        "is_completed": is_line_completed(
            {
                "statusName": status_name,
                "status": _pick(head, "status", "purchaseStatus", default=""),
                "unDeliveryQty": _pick(head, "unDeliveryQty", default=0),
                "unReceiveQty": _pick(head, "unReceiveQty", default=0),
                "batchPurQty": qty,
            }
        ),
        "data_source": "采购单(无行明细)",
        "synced_at": datetime.utcnow(),
    }


def _resolve_completion(status_info: dict) -> bool:
    from srm_client import INCOMPLETE_STATUS_NAMES

    name = (status_info.get("statusName") or "").strip()
    if name in INCOMPLETE_STATUS_NAMES:
        return False
    return True


def _purge_expired_orders(db: Session, customer_id: str) -> int:
    cutoff = retention_cutoff_date()
    removed = 0
    from order_price_service import upsert_from_order

    for row in db.query(SrmOrder).filter(SrmOrder.customer_id == customer_id).all():
        d = parse_order_date(row.purchase_date or row.doc_date)
        if d and d < cutoff:
            upsert_from_order(db, row, source="purge_keep_price")
            db.delete(row)
            removed += 1
    return removed


def _append_new_order(new_orders: list, order_data: dict) -> None:
    new_orders.append(
        {
            "customer_id": order_data.get("customer_id"),
            "customer_name": order_data.get("customer_name"),
            "purchase_no": order_data.get("purchase_no"),
            "purchase_seq": order_data.get("purchase_seq"),
            "purchase_phase_seq": order_data.get("purchase_phase_seq"),
            "product_goods_no": order_data.get("product_goods_no"),
            "product_goods_name": order_data.get("product_goods_name"),
            "batch_pur_qty": order_data.get("batch_pur_qty"),
        }
    )


LOCAL_ARCHIVE_DATA_SOURCE = "订单跟踪(本地归档)"
SRM_IMPORTED_CLOSED_DATA_SOURCE = "订单跟踪(已结案)"


def _should_import_new_order(order_data: dict, existing: Optional[SrmOrder]) -> bool:
    """本系统已有记录继续更新；客户侧早已结案的订单不再新入库。"""
    if existing is not None:
        return True
    return not order_data.get("is_completed")


def _archive_disappeared_orders(db: Session, customer_id: str, synced_keys: set) -> int:
    """从 SRM 进行中列表消失的订单，在本系统标记结案并保留。"""
    if not synced_keys:
        return 0
    rows = (
        db.query(SrmOrder)
        .filter(
            SrmOrder.customer_id == customer_id,
            SrmOrder.line_key.notin_(synced_keys),
            SrmOrder.is_completed.is_(False),
        )
        .all()
    )
    now = datetime.utcnow()
    archived = 0
    from order_price_service import upsert_from_order

    for row in rows:
        if row.data_source == "手动录入":
            continue
        upsert_from_order(db, row, source="local_archive")
        row.is_completed = True
        row.synced_at = now
        row.data_source = LOCAL_ARCHIVE_DATA_SOURCE
        if not row.srm_status_name or row.srm_status_name in ("来料加工", "进行中", "未交完"):
            row.srm_status_name = "已结案"
        archived += 1
    return archived


def _delete_disappeared_orders(db: Session, customer_id: str, synced_keys: set) -> int:
    """不在最新同步列表中的非手工订单：先缓存单价，再删除（客户A ASN 委外口径）。"""
    if not synced_keys:
        return 0
    rows = (
        db.query(SrmOrder)
        .filter(
            SrmOrder.customer_id == customer_id,
            SrmOrder.line_key.notin_(synced_keys),
        )
        .all()
    )
    removed = 0
    from order_price_service import upsert_from_order

    for row in rows:
        if row.data_source == "手动录入":
            continue
        upsert_from_order(db, row, source="delete_keep_price")
        db.delete(row)
        removed += 1
    return removed


def _purge_imported_closed_orders(db: Session, customer_id: str) -> int:
    """清理从 SRM 结案列表误导入的历史订单（非本系统跟进后归档）。"""
    rows = (
        db.query(SrmOrder)
        .filter(
            SrmOrder.customer_id == customer_id,
            SrmOrder.is_completed.is_(True),
            SrmOrder.data_source == SRM_IMPORTED_CLOSED_DATA_SOURCE,
        )
        .all()
    )
    from order_price_service import upsert_from_order

    for row in rows:
        upsert_from_order(db, row, source="purge_closed_keep_price")
        db.delete(row)
    if rows:
        logger.info("%s 清理历史结案导入 %s 行", customer_id, len(rows))
    return len(rows)


def _recover_stale_sync_logs(db: Session) -> None:
    stale = db.query(SyncLog).filter(SyncLog.status == "running").all()
    for log in stale:
        log.status = "failed"
        log.message = "同步中断或超时，请重新同步"
        log.finished_at = datetime.utcnow()


async def _sync_customer_v1(
    db: Session, customer: dict, client: SrmClient, new_orders: Optional[list] = None, kitting_alerts: Optional[list] = None
) -> tuple[int, int, int]:
    order_items, live_total = await client.fetch_all_order_lines()
    synced_keys = set()
    synced = 0

    for item in order_items:
        line = item.get("asn_line")
        if not line:
            # 兼容旧结构（工单+行），正常路径已改为 ASN 委外明细
            wo = item.get("workorder") or {}
            body = item.get("line")
            purchase_no = (wo.get("purchaseNo") or item.get("purchase_no") or "").strip()
            if not purchase_no:
                continue
            head = {}
            if body:
                order_data = _build_order_from_line_v1(customer, wo, body, head)
            else:
                order_data = _build_order_from_workorder_v1(customer, wo, head, None)
        else:
            order_data = _build_order_from_asn_pur_line(customer, line)

        if not order_data.get("purchase_no"):
            continue
        if not is_within_retention(order_data):
            continue

        existing = _find_existing_order(db, customer["id"], order_data)
        if existing and existing.line_key != order_data["line_key"]:
            # 统一到补零后的 line_key
            order_data["line_key"] = existing.line_key
            order_data["purchase_seq"] = existing.purchase_seq
            order_data["purchase_phase_seq"] = existing.purchase_phase_seq

        if existing and not order_data.get("collected_sets_qty"):
            order_data["collected_sets_qty"] = float(existing.collected_sets_qty or 0)

        if not _should_import_new_order(order_data, existing):
            continue

        order_data = _apply_customer_meta(order_data, customer)
        synced_keys.add(order_data["line_key"])
        save_synced_order(db, existing, order_data, new_orders, kitting_alerts)
        synced += 1

    removed = _delete_disappeared_orders(db, customer["id"], synced_keys)
    db.flush()

    expired = _purge_expired_orders(db, customer["id"])
    if expired:
        logger.info("%s 清理超期订单 %s 行", customer["name"], expired)

    return synced, live_total, removed


async def _sync_customer_v2(
    db: Session, customer: dict, client: SrmClientV2, new_orders: Optional[list] = None, kitting_alerts: Optional[list] = None
) -> tuple[int, int, int, int]:
    date_from = retention_cutoff_str()
    try:
        purged_closed = _purge_imported_closed_orders(db, customer["id"])
        order_items, live_total = await client.fetch_all_order_lines(date_from=date_from)
        synced_keys = set()
        synced = 0

        for item in order_items:
            head = item.get("head") or {}
            line = item.get("line")
            if line:
                order_data = _build_order_from_line_v2(customer, head, line, closed=bool(item.get("closed")))
            else:
                order_data = _build_order_from_head_v2(customer, head)

            if not order_data["purchase_no"]:
                continue

            if not is_within_retention(order_data):
                continue

            key = order_data["line_key"]
            existing = db.query(SrmOrder).filter(SrmOrder.line_key == key).first()

            if not _should_import_new_order(order_data, existing):
                continue

            order_data = _apply_customer_meta(order_data, customer)
            synced_keys.add(key)
            save_synced_order(db, existing, order_data, new_orders, kitting_alerts)
            synced += 1

        archived = _archive_disappeared_orders(db, customer["id"], synced_keys)

        removed = _purge_expired_orders(db, customer["id"])
        if removed:
            logger.info("%s 清理超期订单 %s 行", customer["name"], removed)

        return synced, live_total, archived, purged_closed
    finally:
        await client.close()


def _apply_kingdee_price_map_to_orders(db: Session, customer_id: str, price_map: dict) -> int:
    """用 PUR 单价回填已有永联订单金额与单价缓存（含已收货/本地归档行）。"""
    if not price_map:
        return 0
    from order_price_service import upsert_line_price

    updated = 0
    orders = db.query(SrmOrder).filter(SrmOrder.customer_id == customer_id).all()
    for order in orders:
        bill = (order.purchase_no or "").strip()
        mat = (order.product_goods_no or "").strip()
        info = price_map.get((bill, mat))
        if not info:
            continue
        tax_price = float(info.get("tax_price") or 0)
        tax_amount = float(info.get("tax_amount") or 0)
        qty = float(order.batch_pur_qty or 0)
        if tax_amount <= 0 and tax_price > 0 and qty > 0:
            tax_amount = tax_price * qty
        if tax_amount <= 0 and tax_price <= 0:
            continue
        if tax_amount > 0:
            order.tax_amount = tax_amount
            order.no_tax_amount = tax_amount
            order.sum_tax_amount = tax_amount
            order.sum_no_tax_amount = tax_amount
        if upsert_line_price(
            db,
            line_key=order.line_key,
            customer_id=order.customer_id,
            purchase_no=order.purchase_no,
            product_goods_no=order.product_goods_no,
            tax_amount=tax_amount,
            batch_pur_qty=qty,
            tax_price=tax_price,
            source="kingdee_pur_price",
        ):
            updated += 1
    return updated


async def _sync_customer_kingdee(
    db: Session, customer: dict, client: KingdeeScpClient, new_orders: Optional[list] = None, kitting_alerts: Optional[list] = None
) -> tuple[int, int, int]:
    date_from = retention_cutoff_str()
    try:
        order_items, live_total = await client.fetch_all_order_lines(date_from=date_from)

        # SCP 在制列表：无金额、结案易消失。PUR 鼎雄全量补金额 + 结案已收。
        try:
            pur_lines = await client.fetch_supplier_purchase_lines(date_from=date_from)
            price_map = await client.fetch_supplier_price_map(lines=pur_lines)
            scp_by_bm: dict[tuple[str, str], dict] = {}
            for item in order_items:
                line = item.get("line") or {}
                bill = str(line.get("FBillNo") or "").strip()
                mat = str(line.get("FMaterialId.FNumber") or "").strip()
                if bill and mat:
                    scp_by_bm[(bill, mat)] = line

            # 用 PUR 补齐缺失历史行；在制行用 SCP 收货量覆盖 PUR 的 0
            pur_keys: set[tuple[str, str]] = set()
            extra_items: list[dict] = []
            for prow in pur_lines:
                bill = str(prow.get("FBillNo") or "").strip()
                mat = str(prow.get("FMaterialId.FNumber") or "").strip()
                if not bill or not mat:
                    continue
                pur_keys.add((bill, mat))
                scp_line = scp_by_bm.get((bill, mat))
                if scp_line is not None:
                    # 合并金额到在制行
                    if float(prow.get("FTaxPrice") or 0) > 0:
                        scp_line["FTaxPrice"] = prow.get("FTaxPrice")
                    if float(prow.get("FAllAmount") or 0) > 0:
                        scp_line["FAllAmount"] = prow.get("FAllAmount")
                    continue
                extra_items.append({"head": {}, "line": prow, "closed": bool(prow.get("_pur_closed"))})

            if extra_items:
                order_items.extend(extra_items)
                logger.info("%s 从 PUR 补入历史/结案行 %s", customer["name"], len(extra_items))

            # 回填库内已有行金额（含仅存在于本地归档的）
            priced = _apply_kingdee_price_map_to_orders(db, customer["id"], price_map)
            if priced:
                logger.info("%s 回填金蝶单价/金额 %s 行", customer["name"], priced)
        except Exception:
            logger.exception("%s PUR 金额/历史单拉取失败", customer["name"])

        synced_keys = set()
        synced = 0

        for item in order_items:
            line = item.get("line") or {}
            order_data = _build_order_from_line_kingdee(customer, line)
            if not order_data["purchase_no"]:
                continue
            if not is_within_retention(order_data):
                continue

            # 先按单据+料号找已有行，避免 SCP/PUR 分录号不一致导致重复插入
            existing = None
            if order_data.get("product_goods_no"):
                existing = (
                    db.query(SrmOrder)
                    .filter(
                        SrmOrder.customer_id == customer["id"],
                        SrmOrder.purchase_no == order_data["purchase_no"],
                        SrmOrder.product_goods_no == order_data["product_goods_no"],
                    )
                    .first()
                )
            if existing is None:
                existing = db.query(SrmOrder).filter(SrmOrder.line_key == order_data["line_key"]).first()
            # 同事务内已 add 未 flush 的行
            if existing is None:
                for obj in list(db.new):
                    if (
                        isinstance(obj, SrmOrder)
                        and obj.customer_id == customer["id"]
                        and obj.purchase_no == order_data["purchase_no"]
                        and (obj.product_goods_no or "") == (order_data.get("product_goods_no") or "")
                    ):
                        existing = obj
                        break
            if existing and existing.line_key:
                order_data["line_key"] = existing.line_key
            key = order_data["line_key"]

            # 永联结案历史单也要入库：看板按收货×单价，不能只留在制
            allow_closed_history = (
                existing is None
                and bool(order_data.get("is_completed"))
                and (
                    float(order_data.get("tax_amount") or 0) > 0
                    or float(order_data.get("receive_qty") or 0) > 0
                )
            )
            if not _should_import_new_order(order_data, existing) and not allow_closed_history:
                continue

            # 避免 SCP 无金额时把已回填的 tax_amount 冲成 0
            if existing and float(order_data.get("tax_amount") or 0) <= 0 and float(existing.tax_amount or 0) > 0:
                order_data["tax_amount"] = float(existing.tax_amount or 0)
                order_data["no_tax_amount"] = float(existing.no_tax_amount or existing.tax_amount or 0)
                order_data["sum_tax_amount"] = float(existing.sum_tax_amount or existing.tax_amount or 0)
                order_data["sum_no_tax_amount"] = float(existing.sum_no_tax_amount or existing.tax_amount or 0)
            # 本地已有更大收货量时保留（PUR 在制行为 0）
            if existing and float(order_data.get("receive_qty") or 0) < float(existing.receive_qty or 0):
                order_data["receive_qty"] = float(existing.receive_qty or 0)
                rem = max(float(order_data.get("batch_pur_qty") or 0) - float(order_data["receive_qty"]), 0.0)
                order_data["un_receive_qty"] = rem
                order_data["un_delivery_qty"] = rem

            order_data = _apply_customer_meta(order_data, customer)
            synced_keys.add(key)
            save_synced_order(db, existing, order_data, new_orders, kitting_alerts)
            synced += 1

        archived = _archive_disappeared_orders(db, customer["id"], synced_keys)
        removed = _purge_expired_orders(db, customer["id"])
        if removed:
            logger.info("%s 清理超期订单 %s 行", customer["name"], removed)
        return synced, live_total, archived
    finally:
        await client.close()


async def sync_srm_orders(db: Session) -> SyncLog:
    _recover_stale_sync_logs(db)
    db.commit()

    log = SyncLog(status="running", started_at=datetime.utcnow())
    db.add(log)
    db.commit()
    db.refresh(log)

    messages = []
    total_synced = 0
    new_orders: list = []
    kitting_alerts: list = []

    try:
        customers = get_enabled_customers()
        if not customers:
            raise RuntimeError("未配置启用的 SRM 客户")

        for customer in customers:
            client = get_srm_client(customer)
            try:
                if customer.get("api_type") == "v2":
                    synced, live_total, archived, purged_closed = await _sync_customer_v2(
                        db, customer, client, new_orders, kitting_alerts
                    )
                    kit_refreshed = refresh_customer_material_kitting(db, customer["id"], kitting_alerts)
                    if kit_refreshed:
                        messages.append(f"{customer['name']}: 刷新备料齐套 {kit_refreshed} 行")
                elif customer.get("api_type") == "kingdee":
                    synced, live_total, archived = await _sync_customer_kingdee(
                        db, customer, client, new_orders, kitting_alerts
                    )
                else:
                    synced, live_total, archived = await _sync_customer_v1(
                        db, customer, client, new_orders, kitting_alerts
                    )
                incomplete = (
                    db.query(SrmOrder)
                    .filter(SrmOrder.customer_id == customer["id"], SrmOrder.is_completed.is_(False))
                    .count()
                )
                completed = (
                    db.query(SrmOrder)
                    .filter(SrmOrder.customer_id == customer["id"], SrmOrder.is_completed.is_(True))
                    .count()
                )
                api_type = customer.get("api_type") or "v1"
                if api_type == "v2":
                    archive_note = f"，本次归档 {archived} 行" if archived else ""
                    purge_note = f"，清理历史结案 {purged_closed} 行" if purged_closed else ""
                    messages.append(
                        f"{customer['name']}: 更新 {synced} 行（SRM进行中 {live_total} 行），"
                        f"本地进行中 {incomplete}、已归档 {completed} 行{archive_note}{purge_note}"
                    )
                elif api_type == "kingdee":
                    archive_note = f"，本次归档 {archived} 行" if archived else ""
                    messages.append(
                        f"{customer['name']}: 更新 {synced} 行（SRM进行中 {live_total} 行），"
                        f"本地进行中 {incomplete}、已归档 {completed} 行{archive_note}"
                    )
                else:
                    delete_note = f"，本次删除旧数据 {archived} 行" if archived else ""
                    total_local = incomplete + completed
                    messages.append(
                        f"{customer['name']}: 更新 {synced} 行（ASN委外在制 {live_total} 行），"
                        f"本地保留 {total_local} 行{delete_note}"
                    )
                total_synced += synced
            except Exception as exc:
                logger.exception("客户 %s 同步失败", customer.get("name"))
                messages.append(f"{customer['name']}: 失败 - {exc}")

        # 对账明细仍仅同步第一个 v1 客户（恩玖 v2 暂无对账接口）
        recon_count = 0
        for customer in customers:
            if customer.get("api_type") != "v1":
                continue
            try:
                client = get_srm_client(customer)
                recon_records = await client.fetch_all_reconciliation()
                recon_keys = set()
                for rec in recon_records:
                    record_no = (rec.get("invoiceNo") or rec.get("billNo") or rec.get("id") or "")
                    record_no = str(record_no).strip()
                    if not record_no:
                        continue
                    recon_keys.add(record_no)
                    data = {
                        "record_no": record_no,
                        "record_type": "invoice" if rec.get("invoiceNo") else "bill",
                        "record_date": rec.get("invoiceDate") or rec.get("billDate"),
                        "tax_amount": float(rec.get("taxAmount") or rec.get("sumTaxAmount") or 0),
                        "no_tax_amount": float(rec.get("noTaxAmount") or rec.get("sumNoTaxAmount") or 0),
                        "status": str(rec.get("status") or ""),
                        "status_name": rec.get("statusName") or "",
                        "synced_at": datetime.utcnow(),
                    }
                    existing = (
                        db.query(SrmReconciliation).filter(SrmReconciliation.record_no == record_no).first()
                    )
                    if existing:
                        for k, v in data.items():
                            setattr(existing, k, v)
                    else:
                        db.add(SrmReconciliation(**data))
                    recon_count += 1
                if recon_keys:
                    for row in db.query(SrmReconciliation).filter(
                        SrmReconciliation.record_no.notin_(recon_keys)
                    ).all():
                        db.delete(row)
                break
            except Exception as exc:
                logger.warning("对账明细同步跳过: %s", exc)

        db.commit()
        failed = [m for m in messages if "失败" in m]
        if new_orders:
            messages.append(f"新增订单 {len(new_orders)} 行")
        if kitting_alerts:
            messages.append(f"客户齐套提醒 {len(kitting_alerts)} 行")
        log.status = "failed" if failed and total_synced == 0 else ("partial" if failed else "success")
        if log.status != "failed":
            try:
                snap_n = snapshot_receive_qty(db)
                messages.append(f"收货快照写入 {snap_n} 行")
            except Exception as snap_exc:
                logger.exception("收货快照写入失败")
                messages.append(f"收货快照失败 - {snap_exc}")
            try:
                ev = await sync_receive_events(db)
                msg = (
                    f"收货事件 {ev['date_from']}~{ev['date_to']} "
                    f"客户A {ev['feilisi']} / 客户B {ev['enjiu']}"
                )
                if ev.get("errors"):
                    msg += f"（部分失败: {'；'.join(ev['errors'])}）"
                messages.append(msg)
            except Exception as ev_exc:
                logger.exception("收货事件拉取失败")
                detail = str(ev_exc).strip() or type(ev_exc).__name__
                messages.append(f"收货事件失败 - {detail}")
        log.message = (
            f"同步完成（客户A按 ASN 委外在制列表全量对齐；其他客户仍跟进本地归档）："
            + "；".join(messages)
            + f"；对账记录 {recon_count} 条"
        )
        log.orders_synced = total_synced
        log.new_orders_count = len(new_orders)
        log.new_orders_detail = json.dumps(new_orders[:100], ensure_ascii=False) if new_orders else None
        log.kitting_alert_count = len(kitting_alerts)
        log.kitting_alert_detail = json.dumps(kitting_alerts[:100], ensure_ascii=False) if kitting_alerts else None
    except Exception as exc:
        logger.exception("SRM 同步失败")
        log.status = "failed"
        log.message = str(exc)
        db.rollback()
    finally:
        log.finished_at = datetime.utcnow()
        db.add(log)
        db.commit()
        db.refresh(log)

    return log
