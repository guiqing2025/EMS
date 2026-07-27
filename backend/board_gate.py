"""板码全链路卡控公共判定：AOI → 插件 → 后焊 → ICT（须先后焊）→ 三防 → 包装。"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from models import ProcessScanRecord, SrmOrder
from pcba_barcode import is_enjiu_barcode, parse_pcba_barcode

STATION_PLUGIN = "plugin"
STATION_POST_SOLDER = "post_solder"
STATION_COATING = "coating"

STATION_LABELS = {
    STATION_PLUGIN: "插件",
    STATION_POST_SOLDER: "后焊",
    STATION_COATING: "三防",
}

VALID_STATIONS = set(STATION_LABELS)

# 恩玖客户 ID（含别名）
ENJIU_CUSTOMER_IDS = frozenset({"enjiu", "a116"})


def norm_barcode(barcode: str) -> str:
    text = (barcode or "").strip()
    parsed = parse_pcba_barcode(text)
    if parsed:
        return parsed["barcode"]
    # 恩玖条码保持数字；其它转大写
    if is_enjiu_barcode(text):
        return text.strip()
    return text.strip().upper()


def resolve_customer_id(db: Session, *, barcode: str = "", purchase_no: str = "") -> Optional[str]:
    pn = (purchase_no or "").strip()
    if pn:
        order = db.query(SrmOrder).filter(SrmOrder.purchase_no == pn).first()
        if order and order.customer_id:
            return (order.customer_id or "").strip()
    code = norm_barcode(barcode)
    if code:
        row = (
            db.query(ProcessScanRecord.customer_id)
            .filter(
                ProcessScanRecord.barcode == code,
                ProcessScanRecord.customer_id.isnot(None),
                ProcessScanRecord.customer_id != "",
            )
            .order_by(ProcessScanRecord.id.desc())
            .first()
        )
        if row and row[0]:
            return str(row[0]).strip()
        # 人工贴码形态本身视为恩玖
        if is_enjiu_barcode(code):
            return "enjiu"
    return None


def is_enjiu_context(db: Session, *, barcode: str = "", purchase_no: str = "", customer_id: str = "") -> bool:
    cid = (customer_id or "").strip().lower()
    if not cid:
        cid = (resolve_customer_id(db, barcode=barcode, purchase_no=purchase_no) or "").lower()
    if cid in ENJIU_CUSTOMER_IDS:
        return True
    if is_enjiu_barcode(barcode or ""):
        return True
    return False


def is_fail(result: Optional[str]) -> bool:
    t = (result or "").strip().upper()
    if not t:
        return False
    if t in ("FAIL", "FALL", "NG"):
        return True
    if "FAIL" in t or "NG" in t:
        return True
    return False


def is_pass(result: Optional[str]) -> bool:
    t = (result or "").strip().upper()
    if not t:
        return False
    # 恩玖 ATS 原始值为 Success；入库已规范为 PASS，此处兼容未规范数据
    if t in ("PASS", "SUCCESS", "OK"):
        return True
    return t.startswith("P") and "FAIL" not in t


def aoi_for(db: Session, barcode: str) -> Optional[Any]:
    from device_board_archive import find_board_by_barcode

    return find_board_by_barcode(db, barcode, kind="aoi")


def ict_for(db: Session, barcode: str) -> Optional[Any]:
    from device_board_archive import find_board_by_barcode

    return find_board_by_barcode(db, barcode, kind="ict")


def has_station(db: Session, barcode: str, station: str) -> bool:
    return (
        db.query(ProcessScanRecord.id)
        .filter(ProcessScanRecord.barcode == barcode, ProcessScanRecord.station == station)
        .first()
        is not None
    )


def existing_scan(db: Session, barcode: str, station: str) -> Optional[ProcessScanRecord]:
    return (
        db.query(ProcessScanRecord)
        .filter(ProcessScanRecord.barcode == barcode, ProcessScanRecord.station == station)
        .first()
    )


def check_aoi_pass(db: Session, barcode: str) -> dict[str, Any]:
    """插件前置：必须有 AOI 且 PASS。"""
    aoi = aoi_for(db, barcode)
    if not aoi:
        return {"ok": False, "reason": "no_aoi", "message": "未测AOI", "aoi_result": None}
    if is_fail(aoi.result):
        return {
            "ok": False,
            "reason": "aoi_fail",
            "message": "AOI不良",
            "aoi_result": aoi.result,
        }
    if not is_pass(aoi.result):
        return {
            "ok": False,
            "reason": "no_aoi",
            "message": "未测AOI",
            "aoi_result": aoi.result,
        }
    return {"ok": True, "reason": "ok", "message": "", "aoi_result": aoi.result}


def check_ict_effective_pass(db: Session, barcode: str) -> dict[str, Any]:
    """
    ICT 有效 PASS：有 ICT 记录 + PASS + 已有后焊过站。
    无后焊时即使机台有 PASS 也不认（系统侧「不可测/无效」）。
    """
    if not has_station(db, barcode, STATION_POST_SOLDER):
        return {
            "ok": False,
            "reason": "no_post_solder",
            "message": "未过后焊工序",
            "ict_result": None,
            "valid_for_pass": False,
        }
    ict = ict_for(db, barcode)
    if not ict:
        return {
            "ok": False,
            "reason": "no_ict",
            "message": "未测ICT",
            "ict_result": None,
            "valid_for_pass": False,
        }
    if is_fail(ict.result):
        return {
            "ok": False,
            "reason": "ict_fail",
            "message": "ICT不良",
            "ict_result": ict.result,
            "valid_for_pass": False,
        }
    if not is_pass(ict.result):
        return {
            "ok": False,
            "reason": "no_ict",
            "message": "未测ICT",
            "ict_result": ict.result,
            "valid_for_pass": False,
        }
    return {
        "ok": True,
        "reason": "ok",
        "message": "",
        "ict_result": ict.result,
        "valid_for_pass": True,
    }


def ict_valid_for_pass(db: Session, barcode: str) -> bool:
    """看板用：该条码 ICT PASS 是否可被下游认可（须先后焊）。"""
    code = norm_barcode(barcode)
    if not code:
        return False
    ict = ict_for(db, code)
    if not ict or not is_pass(ict.result) or is_fail(ict.result):
        return False
    return has_station(db, code, STATION_POST_SOLDER)


def check_packing_gate(db: Session, barcode: str) -> dict[str, Any]:
    """
    包装入库卡控：仅验三防过站（有过站记录即视为 PASS）。
    插件/后焊/AOI/ICT 由上游工序自行卡控，入库不再重复查。
    """
    code = norm_barcode(barcode)
    if not code:
        return {"ok": False, "reason": "empty", "message": "条码不能为空", "barcode": ""}

    if not has_station(db, code, STATION_COATING):
        return {"ok": False, "reason": "no_coating", "message": "未过三防工序", "barcode": code}

    return {"ok": True, "reason": "ok", "message": "", "barcode": code}
