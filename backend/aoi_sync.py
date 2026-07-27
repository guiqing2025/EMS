"""从 AOI 共享盘 mes_txt 抓取 CSV，按镭雕规则归属采购单。支持多机。"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import load_config
from laser_service import find_laser_batch_for_barcode
from models import AoiBoardResult, AoiSyncFile
from pcba_barcode import parse_pcba_barcode

logger = logging.getLogger(__name__)

# 常见表头别名
BARCODE_KEYS = ("条码", "barcode", "Barcode", "BARCODE", "序列号", "SN", "板号")
RESULT_KEYS = ("测试结果", "结果", "Result", "result", "STATUS", "Status")
SIDE_KEYS = ("面", "Side", "side", "PCB面")
PRODUCT_KEYS = ("产品名称", "品名", "Product", "product", "机型")
MACHINE_KEYS = ("机器编号", "机器", "Machine", "machine")
LINE_KEYS = ("线别", "线体", "Line", "line")
TIME_KEYS = (
    "测试时间",
    "测试日期",
    "检测时间",
    "TestTime",
    "Test Time",
    "Datetime",
    "DateTime",
    "datetime",
)
# 「测试用时」是时长秒数，不是时刻，勿纳入 TIME_KEYS
_FILENAME_TS = re.compile(r"(?<!\d)(\d{14})(?:\.\w+)?$", re.IGNORECASE)


def _aoi_cfg() -> dict[str, Any]:
    cfg = load_config()
    aoi = cfg.get("aoi") or {}
    share = aoi.get("share") or "mes_txt"
    username = aoi.get("username") or "A"
    password = aoi.get("password") or "000000"
    max_files = int(aoi.get("max_files_per_sync") or 0)
    lookback_days = int(aoi.get("lookback_days") or 14)
    machines = aoi.get("machines")
    if isinstance(machines, list) and machines:
        out_machines = []
        for i, m in enumerate(machines):
            if not isinstance(m, dict):
                continue
            host = (m.get("host") or "").strip()
            if not host:
                continue
            mid = (m.get("id") or f"aoi-{host.split('.')[-1]}").strip()
            out_machines.append(
                {
                    "id": mid,
                    "host": host,
                    "share": (m.get("share") or share).strip() or share,
                    "username": (m.get("username") or username).strip() or username,
                    "password": m.get("password") if m.get("password") is not None else password,
                }
            )
        if out_machines:
            return {"machines": out_machines, "max_files": max_files, "lookback_days": lookback_days}
    # 兼容旧单机配置
    host = (aoi.get("host") or "192.168.2.115").strip()
    return {
        "machines": [
            {
                "id": "aoi-115",
                "host": host,
                "share": share,
                "username": username,
                "password": password,
            }
        ],
        "max_files": max_files,
        "lookback_days": lookback_days,
    }


def _pick(row: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        if k in row and row[k] is not None and str(row[k]).strip():
            return str(row[k]).strip()
    lower_map = {str(k).strip().lower(): v for k, v in row.items()}
    for k in keys:
        v = lower_map.get(k.lower())
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _parse_tested_at(raw: str) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    # 纯数字时长（如「测试用时」8.284）不当作时间
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def _tested_at_from_filename(name: str) -> Optional[datetime]:
    """AOI 机台 CSV 文件名末尾常带 YYYYMMDDHHMMSS（CSV 内无测试时刻列）。"""
    base = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    # 兼容 source_file「host:filename」
    if ":" in base and not base.startswith("\\\\"):
        base = base.split(":", 1)[-1]
    m = _FILENAME_TS.search(base)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _normalize_result(raw: str) -> str:
    t = (raw or "").strip().upper()
    if not t:
        return "UNKNOWN"
    if "PASS" in t or t in ("OK", "良", "合格"):
        return "PASS"
    if "FAIL" in t or "FALL" in t or "NG" in t or t in ("不良", "不合格"):
        return "FAIL"
    return t[:16]


def _parse_csv_bytes(data: bytes) -> list[dict]:
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    header_idx = 0
    for i, line in enumerate(lines[:30]):
        if any(k in line for k in ("条码", "Barcode", "barcode")):
            header_idx = i
            break
    sample = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(sample))
    return [dict(r) for r in reader if r]


def _upsert_board(db: Session, payload: dict) -> None:
    barcode = payload["barcode"]
    row = db.query(AoiBoardResult).filter(AoiBoardResult.barcode == barcode).first()
    now = datetime.utcnow()
    if not row:
        row = AoiBoardResult(barcode=barcode, synced_at=now)
        db.add(row)
    for k, v in payload.items():
        setattr(row, k, v)
    row.synced_at = now
    batch = find_laser_batch_for_barcode(db, barcode)
    if batch:
        row.purchase_no = batch.purchase_no
        row.customer_id = batch.customer_id
        row.laser_batch_id = batch.id
        row.model_code = batch.model_code


def _sync_one_machine(
    db: Session,
    machine: dict[str, Any],
    *,
    max_files: int,
    force_all: bool,
    lookback_days: int = 14,
) -> dict[str, Any]:
    from smbclient import listdir, open_file, register_session, reset_connection_cache, stat

    mid = machine["id"]
    host = machine["host"]
    share = machine["share"]
    root = rf"\\{host}\{share}"
    out: dict[str, Any] = {
        "machine_id": mid,
        "host": host,
        "share": root,
        "files_seen": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "boards_upserted": 0,
        "errors": [],
    }

    reset_connection_cache()
    try:
        register_session(
            host,
            username=machine["username"],
            password=machine["password"],
            connection_timeout=12,
        )
        names = listdir(root)
    except Exception as e:
        out["errors"].append(f"无法访问 {root}：{e}")
        return out

    entries: list[tuple[str, float, int, str]] = []
    for name in names:
        lower = name.lower()
        if not (lower.endswith(".csv") or lower.endswith(".txt")):
            continue
        path = rf"{root}\{name}"
        try:
            st = stat(path)
            entries.append((name, float(st.st_mtime), int(st.st_size), path))
        except Exception:
            continue
    out["files_seen"] = len(entries)
    entries.sort(key=lambda x: x[1], reverse=True)

    cutoff = None
    if lookback_days > 0 and not force_all:
        cutoff = datetime.now().timestamp() - lookback_days * 86400
    if cutoff is not None:
        kept: list[tuple[str, float, int, str]] = []
        for name, mtime, size, path in entries:
            if mtime < cutoff:
                out["files_skipped"] += 1
                continue
            kept.append((name, mtime, size, path))
        entries = kept

    if max_files and max_files > 0:
        entries = entries[:max_files]

    for name, mtime, size, path in entries:
        prev = (
            db.query(AoiSyncFile)
            .filter(AoiSyncFile.machine_id == mid, AoiSyncFile.filename == name)
            .first()
        )
        # 兼容旧数据：仅 filename、无 machine_id 的记录视为第一台历史
        if prev is None and mid in ("aoi-115", "192.168.2.115"):
            prev = (
                db.query(AoiSyncFile)
                .filter(
                    (AoiSyncFile.machine_id.is_(None)) | (AoiSyncFile.machine_id == ""),
                    AoiSyncFile.filename == name,
                )
                .first()
            )
            if prev is not None:
                prev.machine_id = mid
        if (
            not force_all
            and prev
            and prev.file_mtime
            and abs(float(prev.file_mtime) - mtime) < 0.5
            and prev.file_size == size
        ):
            out["files_skipped"] += 1
            continue
        try:
            with open_file(path, mode="rb") as f:
                data = f.read()
            rows = _parse_csv_bytes(data)
            count = 0
            for raw in rows:
                barcode = _pick(raw, BARCODE_KEYS)
                if not barcode:
                    continue
                barcode = barcode.strip().upper()
                if barcode in ("NULL", "NONE", "N/A", "-", "—"):
                    continue
                parsed = parse_pcba_barcode(barcode)
                if not parsed:
                    continue
                tested_at = _parse_tested_at(_pick(raw, TIME_KEYS)) or _tested_at_from_filename(name)
                payload = {
                    "barcode": parsed["barcode"],
                    "product_name": _pick(raw, PRODUCT_KEYS) or None,
                    "side": _pick(raw, SIDE_KEYS) or None,
                    "result": _normalize_result(_pick(raw, RESULT_KEYS)),
                    "machine": _pick(raw, MACHINE_KEYS) or mid,
                    "line_name": _pick(raw, LINE_KEYS) or None,
                    "tested_at": tested_at,
                    "source_file": f"{host}:{name}",
                    "model_mid": parsed["model_mid"],
                    "model_ver": parsed["model_ver"],
                    "laser_date": parsed["laser_date"],
                    "seq": parsed["seq"],
                    "model_code": parsed["model_code_guess"],
                }
                _upsert_board(db, payload)
                count += 1
                out["boards_upserted"] += 1
            if prev:
                prev.file_mtime = mtime
                prev.file_size = size
                prev.row_count = count
                prev.processed_at = datetime.utcnow()
                prev.machine_id = mid
            else:
                db.add(
                    AoiSyncFile(
                        machine_id=mid,
                        filename=name,
                        file_mtime=mtime,
                        file_size=size,
                        row_count=count,
                        processed_at=datetime.utcnow(),
                    )
                )
            out["files_processed"] += 1
            db.flush()
        except Exception as e:
            logger.exception("AOI 文件处理失败 %s %s", mid, name)
            try:
                db.rollback()
            except Exception:
                pass
            out["errors"].append(f"{name}: {e}")
            if len(out["errors"]) >= 15:
                break

    try:
        db.commit()
    except Exception as e:
        logger.exception("AOI 提交失败 %s", mid)
        db.rollback()
        out["errors"].append(f"commit: {e}")
    return out


def sync_aoi_from_share(db: Session, *, force_all: bool = False) -> dict[str, Any]:
    """抓取配置中全部 AOI 机台 CSV 并入库。"""
    cfg = _aoi_cfg()
    machines = cfg["machines"]
    results = []
    total = {
        "machines": results,
        "files_seen": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "boards_upserted": 0,
        "errors": [],
        "share": ",".join(f"\\\\{m['host']}\\{m['share']}" for m in machines),
    }
    for m in machines:
        one = _sync_one_machine(
            db,
            m,
            max_files=cfg["max_files"],
            force_all=force_all,
            lookback_days=0 if force_all else int(cfg.get("lookback_days") or 14),
        )
        results.append(one)
        total["files_seen"] += int(one.get("files_seen") or 0)
        total["files_processed"] += int(one.get("files_processed") or 0)
        total["files_skipped"] += int(one.get("files_skipped") or 0)
        total["boards_upserted"] += int(one.get("boards_upserted") or 0)
        for err in one.get("errors") or []:
            total["errors"].append(f"{one.get('machine_id')}: {err}")
        logger.info(
            "AOI sync %s processed=%s upserted=%s errors=%s",
            one.get("machine_id"),
            one.get("files_processed"),
            one.get("boards_upserted"),
            len(one.get("errors") or []),
        )
    return total
