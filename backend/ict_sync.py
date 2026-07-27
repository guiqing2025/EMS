"""从三台 TRI ICT 机共享盘抓取 .dcl 测试记录，按镭雕规则归属采购单。"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import load_config
from laser_service import find_laser_batch_for_barcode
from models import IctBoardResult, IctSyncFile, LaserBatch
from pcba_barcode import parse_pcba_barcode

logger = logging.getLogger(__name__)

# machine_id -> unix timestamp；登录失败后冷却，避免把 Windows 账户锁死
_LOGIN_COOLDOWN_UNTIL: dict[str, float] = {}
# 午休等降频窗口：上次实际执行 ICT 同步的时间
_LAST_ICT_SYNC_AT: float = 0.0

HEADER_RE = re.compile(
    r"^(PASS|FAIL)\s*,\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*([^,]*)",
    re.I,
)
NAME_RE = re.compile(r"^(?P<code>.+?)(?P<result>PASS|FAIL)\.dcl$", re.I)


def _parse_hhmm(text: str) -> int:
    """'08:00' → 当天分钟数。"""
    parts = (text or "0:0").strip().split(":")
    h = int(parts[0] or 0)
    m = int(parts[1] or 0) if len(parts) > 1 else 0
    return h * 60 + m


def should_run_sync_windows(
    cfg: dict[str, Any],
    last_ran_at: float,
    *,
    skip_label: str = "同步",
) -> tuple[bool, str]:
    """按 sync_windows 判断是否应执行（菲利斯 ICT / 恩玖 ATS 共用）。

    窗口内无 interval_minutes → 按调度间隔全力同步；
    有 interval_minutes（如午休 30）→ 距 last_ran_at 至少该分钟数才跑；
    不在任何窗口 → 跳过。
    """
    windows = cfg.get("sync_windows") or []
    if not windows:
        return True, "未配置时间窗，始终同步"

    try:
        from zoneinfo import ZoneInfo

        tz_name = (cfg.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai"
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now = datetime.now()

    minutes = now.hour * 60 + now.minute
    for w in windows:
        if not isinstance(w, dict):
            continue
        start = _parse_hhmm(str(w.get("start") or "00:00"))
        end = _parse_hhmm(str(w.get("end") or "24:00"))
        if not (start <= minutes < end):
            continue
        label = f"{w.get('start')}-{w.get('end')}"
        reduced = int(w.get("interval_minutes") or 0)
        if reduced <= 0:
            return True, f"测试窗口 {label}"
        elapsed = time.time() - float(last_ran_at or 0)
        need = reduced * 60
        if elapsed >= need:
            return True, f"降频窗口 {label}（每 {reduced} 分钟）"
        remain = int(need - elapsed)
        return False, f"降频窗口 {label}，{remain}s 后再{skip_label}"
    return False, f"非测试时段，跳过{skip_label}"


def should_run_ict_sync(ict: Optional[dict[str, Any]] = None) -> tuple[bool, str]:
    """按 sync_windows 判断当前是否应执行 ICT 同步。"""
    cfg = ict if ict is not None else (_ict_cfg_raw())
    return should_run_sync_windows(cfg, _LAST_ICT_SYNC_AT, skip_label=" ICT 同步")


def mark_ict_sync_ran() -> None:
    global _LAST_ICT_SYNC_AT
    _LAST_ICT_SYNC_AT = time.time()


def _ict_cfg_raw() -> dict[str, Any]:
    return load_config().get("ict") or {}


def _ict_cfg() -> dict[str, Any]:
    cfg = load_config()
    ict = cfg.get("ict") or {}
    return {
        "auto_sync_enabled": bool(ict.get("auto_sync_enabled", False)),
        "sync_interval_minutes": int(ict.get("sync_interval_minutes") or 10),
        "max_files_per_sync": int(ict.get("max_files_per_sync") or 800),
        "lookback_days": int(ict.get("lookback_days") or 7),
        "share": (ict.get("share") or "ICT测试记录").strip(),
        "subpath": (ict.get("subpath") or "test1").strip(),
        "machines": list(ict.get("machines") or []),
        "sync_windows": list(ict.get("sync_windows") or []),
        "timezone": (ict.get("timezone") or "Asia/Shanghai").strip(),
    }


def _decode_dcl(data: bytes) -> str:
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="ignore")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="ignore")
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _normalize_result(raw: str) -> str:
    t = (raw or "").strip().upper()
    if not t:
        return "UNKNOWN"
    if t.startswith("P") or "PASS" in t or t in ("OK", "良", "合格"):
        return "PASS"
    if t.startswith("F") or "FAIL" in t or "NG" in t or t in ("不良", "不合格"):
        return "FAIL"
    return t[:16]


def _parse_tested_at(date_s: str, time_s: str) -> Optional[datetime]:
    d = (date_s or "").strip()
    t = (time_s or "").strip()
    if not d:
        return None
    # TRI: YYYYMMDD + HHMMSS
    if re.fullmatch(r"\d{8}", d) and re.fullmatch(r"\d{6}", t or "000000"):
        try:
            return datetime.strptime(d + (t or "000000"), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(f"{d} {t}".strip(), fmt)
        except ValueError:
            continue
    return None


def parse_dcl_bytes(data: bytes, *, filename: str = "") -> Optional[dict[str, Any]]:
    """解析 TRI .dcl，返回单板头信息。"""
    text = _decode_dcl(data).replace("\r\n", "\n").replace("\r", "\n")
    header_line = ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if s.upper().startswith("PASS") or s.upper().startswith("FAIL"):
            header_line = s
            break
    barcode = ""
    result = "UNKNOWN"
    board_name = None
    ict_id = None
    tested_at = None
    if header_line:
        m = HEADER_RE.match(header_line)
        if m:
            result = _normalize_result(m.group(1))
            ict_id = (m.group(2) or "").strip() or None
            board_name = (m.group(4) or "").strip() or None
            barcode = (m.group(5) or "").strip()
            tested_at = _parse_tested_at(m.group(6), m.group(7))
    if not barcode and filename:
        nm = NAME_RE.match(filename.strip())
        if nm:
            barcode = nm.group("code").strip()
            result = _normalize_result(nm.group("result"))
    barcode = (barcode or "").strip().upper()
    if not barcode or barcode in ("NULL", "NONE", "N/A", "-", "—"):
        return None
    parsed = parse_pcba_barcode(barcode)
    payload: dict[str, Any] = {
        "barcode": parsed["barcode"] if parsed else barcode,
        "board_name": board_name,
        "result": result,
        "ict_id": ict_id,
        "tested_at": tested_at,
        "model_mid": parsed["model_mid"] if parsed else None,
        "model_ver": parsed["model_ver"] if parsed else None,
        "laser_date": parsed["laser_date"] if parsed else None,
        "seq": parsed["seq"] if parsed else None,
        "model_code": (parsed["model_code_guess"] if parsed else None) or board_name,
    }
    # BoardName 常含机型料号前缀，如 120-200235-07 或 03019413-...
    if not payload.get("model_code") and board_name:
        payload["model_code"] = board_name.split("-")[0] if board_name else None
    if board_name and re.match(r"^\d{3}-\d{6}-\d{2}", board_name):
        payload["model_code"] = board_name.split(",")[0].strip()
        m2 = re.match(r"^(\d{3}-\d{6}-\d{2})", board_name)
        if m2:
            payload["model_code"] = m2.group(1)
    return payload


def _upsert_board(
    db: Session,
    payload: dict[str, Any],
    cache: Optional[dict[str, IctBoardResult]] = None,
) -> None:
    barcode = payload["barcode"]
    row = cache.get(barcode) if cache is not None else None
    if row is None:
        row = db.query(IctBoardResult).filter(IctBoardResult.barcode == barcode).first()
    now = datetime.utcnow()
    if not row:
        row = IctBoardResult(barcode=barcode, synced_at=now)
        db.add(row)
    else:
        # 保留更新的测试（按 tested_at）
        old_t = row.tested_at
        new_t = payload.get("tested_at")
        if old_t and new_t and new_t < old_t:
            if cache is not None:
                cache[barcode] = row
            return
    for k, v in payload.items():
        setattr(row, k, v)
    row.synced_at = now
    batch = find_laser_batch_for_barcode(db, barcode)
    if batch:
        row.purchase_no = batch.purchase_no
        row.customer_id = batch.customer_id
        row.laser_batch_id = batch.id
        # 订单机型以贴码/镭雕登记为准；板名留在 board_name
        if batch.model_code:
            row.model_code = batch.model_code
    if cache is not None:
        cache[barcode] = row


def rematch_ict_to_laser(
    db: Session,
    limit: int = 5000,
    *,
    offset: int = 0,
    prefer_known_prefix: bool = True,
) -> dict[str, int]:
    """将尚未归属采购单的 ICT 条码按镭雕/贴码登记挂单。

    - flush：同事务内下一页不再重复扫已挂行
    - offset：当前页全不可挂时跳过（避免死循环扫同一批）
    - prefer_known_prefix：优先扫「前缀已在 laser_batches」或 D0 镭雕形态，恩玖导入后更快挂全
    """
    from sqlalchemy import func, or_

    unmatched = (IctBoardResult.purchase_no.is_(None)) | (IctBoardResult.purchase_no == "")
    q = db.query(IctBoardResult).filter(unmatched)
    if prefer_known_prefix:
        prefix_sq = (
            db.query(LaserBatch.barcode_prefix)
            .filter(
                LaserBatch.barcode_prefix.isnot(None),
                LaserBatch.barcode_prefix != "",
            )
            .distinct()
        )
        prefixes = [p for (p,) in prefix_sq.all() if p]
        if prefixes:
            # 恩玖 16 位：left(barcode,12) ∈ 已登记前缀；菲利斯：D0…
            q = q.filter(
                or_(
                    func.left(IctBoardResult.barcode, 12).in_(prefixes),
                    IctBoardResult.barcode.ilike("D0%"),
                    IctBoardResult.barcode.ilike("DS%"),
                )
            )
    rows = q.order_by(IctBoardResult.id.desc()).offset(offset).limit(limit).all()
    linked = 0
    for row in rows:
        batch = find_laser_batch_for_barcode(db, row.barcode)
        if not batch:
            continue
        row.purchase_no = batch.purchase_no
        row.customer_id = batch.customer_id
        row.laser_batch_id = batch.id
        if batch.model_code:
            row.model_code = batch.model_code
        linked += 1
    if linked:
        db.flush()
    return {"scanned": len(rows), "linked": linked}


def _sync_one_machine(
    db: Session,
    machine: dict[str, Any],
    *,
    share: str,
    subpath: str,
    force_all: bool,
    max_files: int,
    lookback_days: int,
) -> dict[str, Any]:
    from smbclient import open_file, register_session, reset_connection_cache, scandir, stat

    mid = (machine.get("id") or machine.get("host") or "ict").strip()
    host = (machine.get("host") or "").strip()
    user = (machine.get("username") or "Administrator").strip()
    pwd = machine.get("password") or ""
    root = rf"\\{host}\{share}\{subpath}".rstrip("\\")
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
    if not host:
        out["errors"].append("缺少 host")
        return out

    # 登录失败后冷却，避免 Windows 账户锁定（每 2 分钟重试会把 Administrator 锁死）
    now_ts = time.time()
    cool_until = float(_LOGIN_COOLDOWN_UNTIL.get(mid) or 0)
    if cool_until > now_ts:
        remain = int(cool_until - now_ts)
        out["errors"].append(f"登录冷却中，{remain}s 后重试（防止账户锁定）")
        return out

    reset_connection_cache()
    try:
        register_session(
            host,
            username=user,
            password=pwd,
            encrypt=False,
            auth_protocol="ntlm",
            connection_timeout=20,
        )
        _LOGIN_COOLDOWN_UNTIL.pop(mid, None)
    except Exception as e:
        msg = str(e)
        # 认证/锁定类错误：冷却 20 分钟；纯网络超时稍短
        locked = "0xc0000234" in msg.lower() or "locked" in msg.lower() or "0xc000006d" in msg.lower()
        cool_sec = 20 * 60 if locked or "logon" in msg.lower() or "authentication" in msg.lower() else 5 * 60
        _LOGIN_COOLDOWN_UNTIL[mid] = now_ts + cool_sec
        out["errors"].append(f"登录失败: {e}（已冷却 {cool_sec // 60} 分钟）")
        return out

    # 先 SMB 枚举，再按「当前目录文件名」批量查库；绝不 .all() 历史全表
    raw_entries: list[tuple[str, float, int, str]] = []
    try:
        for entry in scandir(root):
            name = entry.name
            if not name.lower().endswith(".dcl"):
                continue
            path = rf"{root}\{name}"
            try:
                # 优先用目录枚举自带的 smb_info，避免每个文件再走一轮 STAT
                info = getattr(entry, "smb_info", None)
                if info is not None and getattr(info, "last_write_time", None) is not None:
                    mtime = float(info.last_write_time.timestamp())
                    size = int(getattr(info, "end_of_file", 0) or 0)
                else:
                    st = entry.stat() if hasattr(entry, "stat") else stat(path)
                    mtime = float(st.st_mtime)
                    size = int(st.st_size or 0)
            except Exception:
                continue
            raw_entries.append((name, mtime, size, path))
    except Exception as e:
        out["errors"].append(f"列举失败: {e}")
        return out

    cutoff = None
    if lookback_days > 0 and not force_all:
        cutoff = datetime.now().timestamp() - lookback_days * 86400

    # lookback 之外的直接跳过，避免对共享盘上「历史堆积」的文件名做 IN 查询
    candidates: list[tuple[str, float, int, str]] = []
    for name, mtime, size, path in raw_entries:
        if cutoff is not None and mtime < cutoff:
            out["files_skipped"] += 1
            continue
        candidates.append((name, mtime, size, path))

    # 仅加载候选文件名元数据（轻量列，分片 IN）
    prev_meta: dict[str, tuple[Optional[float], Optional[int]]] = {}
    names = [n for n, _, _, _ in candidates]
    chunk_size = 800
    for i in range(0, len(names), chunk_size):
        chunk = names[i : i + chunk_size]
        rows = (
            db.query(IctSyncFile.filename, IctSyncFile.file_mtime, IctSyncFile.file_size)
            .filter(IctSyncFile.machine_id == mid, IctSyncFile.filename.in_(chunk))
            .all()
        )
        for filename, file_mtime, file_size in rows:
            prev_meta[str(filename)] = (
                float(file_mtime) if file_mtime is not None else None,
                int(file_size) if file_size is not None else None,
            )
    # 结束只读事务，避免随后读文件/解析时长时间 idle in transaction
    try:
        db.commit()
    except Exception:
        db.rollback()

    entries: list[tuple[str, float, int, str]] = []
    for name, mtime, size, path in candidates:
        prev = prev_meta.get(name)
        if (
            not force_all
            and prev
            and prev[0] is not None
            and abs(float(prev[0]) - mtime) < 0.5
            and prev[1] == size
        ):
            out["files_skipped"] += 1
            continue
        entries.append((name, mtime, size, path))

    out["files_seen"] = len(raw_entries)
    entries.sort(key=lambda x: x[1], reverse=True)
    if max_files > 0:
        entries = entries[:max_files]

    board_cache: dict[str, IctBoardResult] = {}
    for name, mtime, size, path in entries:
        try:
            with open_file(path, mode="rb") as f:
                data = f.read()
            parsed = parse_dcl_bytes(data, filename=name)
            count = 0
            if parsed:
                parsed["source_file"] = name
                parsed["source_host"] = host
                parsed["machine_id"] = mid
                _upsert_board(db, parsed, board_cache)
                count = 1
                out["boards_upserted"] += 1
            prev_row = (
                db.query(IctSyncFile)
                .filter(IctSyncFile.machine_id == mid, IctSyncFile.filename == name)
                .first()
            )
            now = datetime.utcnow()
            if prev_row:
                prev_row.file_mtime = mtime
                prev_row.file_size = size
                prev_row.row_count = count
                prev_row.processed_at = now
            else:
                db.add(
                    IctSyncFile(
                        machine_id=mid,
                        filename=name,
                        file_mtime=mtime,
                        file_size=size,
                        row_count=count,
                        processed_at=now,
                    )
                )
            prev_meta[name] = (mtime, size)
            out["files_processed"] += 1
            if out["files_processed"] % 200 == 0:
                db.commit()
        except Exception as e:
            logger.exception("ICT 文件处理失败 %s %s", mid, name)
            try:
                db.rollback()
            except Exception:
                pass
            board_cache.clear()
            out["errors"].append(f"{name}: {e}")
            if len(out["errors"]) >= 20:
                break
    try:
        db.commit()
    except Exception as e:
        logger.exception("ICT 提交失败 %s", mid)
        db.rollback()
        out["errors"].append(f"commit: {e}")
    return out


def sync_ict_from_shares(db: Session, *, force_all: bool = False) -> dict[str, Any]:
    """抓取配置中全部 ICT 机台 .dcl 并入库。"""
    cfg = _ict_cfg()
    machines = cfg["machines"]
    if not machines:
        return {"status": "failed", "message": "未配置 ict.machines", "machines": []}
    results = []
    for m in machines:
        one = _sync_one_machine(
            db,
            m,
            share=cfg["share"],
            subpath=cfg["subpath"],
            force_all=force_all,
            max_files=cfg["max_files_per_sync"],
            lookback_days=0 if force_all else cfg["lookback_days"],
        )
        results.append(one)
        errs = one.get("errors") or []
        if errs:
            logger.warning(
                "ICT sync %s processed=%s upserted=%s errors=%s sample=%s",
                one.get("machine_id"),
                one.get("files_processed"),
                one.get("boards_upserted"),
                len(errs),
                errs[0],
            )
        else:
            logger.info(
                "ICT sync %s processed=%s upserted=%s errors=0",
                one.get("machine_id"),
                one.get("files_processed"),
                one.get("boards_upserted"),
            )
    return {
        "status": "ok",
        "machines": results,
        "boards_upserted": sum(int(r.get("boards_upserted") or 0) for r in results),
        "files_processed": sum(int(r.get("files_processed") or 0) for r in results),
    }


def boards_for_ict_purchase(
    db: Session,
    purchase_no: str,
    *,
    customer_id: str = "",
    keyword: str = "",
    result: str = "",
    include_items: bool = True,
    limit: int = 5000,
) -> dict[str, Any]:
    from sqlalchemy import func

    pn = (purchase_no or "").strip()
    from device_board_archive import purchase_board_stats

    stats = purchase_board_stats(db, pn, kind="ict", customer_id=customer_id)
    total_n = stats["total"]
    pass_n = stats["pass_count"]
    fail_n = stats["fail_count"]

    base = db.query(IctBoardResult).filter(IctBoardResult.purchase_no == pn)
    if customer_id:
        base = base.filter(IctBoardResult.customer_id == customer_id)

    result_u = func.upper(IctBoardResult.result)
    is_pass = result_u == "PASS"

    items: list[dict] = []
    items_truncated = False
    result_filter = (result or "").strip().upper()
    kw = (keyword or "").strip()
    if include_items and (kw or result_filter):
        q = base
        if kw:
            q = q.filter(IctBoardResult.barcode.like(f"%{kw}%"))
        if result_filter in ("FAIL", "FALL", "NG"):
            q = q.filter(result_u.in_(("FAIL", "FALL", "NG")))
        elif result_filter == "PASS":
            q = q.filter(is_pass)
        rows = q.order_by(IctBoardResult.tested_at.desc(), IctBoardResult.id.desc()).limit(limit + 1).all()
        if len(rows) > limit:
            items_truncated = True
            rows = rows[:limit]
        from board_gate import STATION_POST_SOLDER, has_station, is_pass

        post_solder_ok: dict[str, bool] = {}
        for r in rows:
            bc = (r.barcode or "").strip()
            if bc not in post_solder_ok:
                post_solder_ok[bc] = has_station(db, bc, STATION_POST_SOLDER) if bc else False
            items.append(
                {
                    "barcode": r.barcode,
                    "model_code": r.model_code,
                    "board_name": r.board_name,
                    "result": r.result,
                    "machine_id": r.machine_id,
                    "tested_at": r.tested_at.isoformat(sep=" ", timespec="seconds") if r.tested_at else None,
                    "source_file": r.source_file,
                    "source_host": r.source_host,
                    "valid_for_pass": bool(is_pass(r.result) and post_solder_ok.get(bc)),
                }
            )

    return {
        "purchase_no": pn,
        "total": total_n,
        "pass_count": pass_n,
        "fail_count": fail_n,
        "unknown_count": max(0, total_n - pass_n - fail_n),
        "items_limit": limit,
        "items_truncated": items_truncated,
        "result_filter": result_filter or "",
        "items": items,
    }
