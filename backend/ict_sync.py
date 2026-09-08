"""从 TRI ICT 机共享盘抓取 .dcl 测试记录，按镭雕规则归属采购单。

现网在用机台（可连通）：ICT-115 / ICT-119 / ICT-126。
下线不再同步：ICT-108 / ICT-129 / ICT-136。
恩玖 ICT-157 / ICT-158 走 enjiu_ats_sync。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import load_config
from database import SessionLocal
from laser_service import find_laser_batch_for_barcode
from models import IctBoardResult, IctSyncFile, LaserBatch
from pcba_barcode import parse_pcba_barcode

logger = logging.getLogger(__name__)

# machine_id -> unix timestamp；登录失败后冷却，避免把 Windows 账户锁死
_LOGIN_COOLDOWN_UNTIL: dict[str, float] = {}
# 午休等降频窗口：上次实际执行 ICT 同步的时间
_LAST_ICT_SYNC_AT: float = 0.0
# 单机同步超时（秒）：lookback 枚举 + 缺口补扫可能更久，避免误杀
_MACHINE_SYNC_TIMEOUT_SEC = 360
# 水位重叠：用已同步最大 mtime 往回多看一段时间，避免时钟/漏抓
_WATERMARK_OVERLAP_SEC = 7200

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
    max_files = int(ict.get("max_files_per_sync") or 800)
    # 缺口补扫配额：默认不超过每轮上限的一半，至少 200（可配置）
    gap_raw = ict.get("gap_fill_max_files")
    if gap_raw is None:
        gap_fill = max(200, min(800, max_files // 2 if max_files > 0 else 800))
    else:
        gap_fill = max(0, int(gap_raw))
    return {
        "auto_sync_enabled": bool(ict.get("auto_sync_enabled", False)),
        "sync_interval_minutes": int(ict.get("sync_interval_minutes") or 10),
        "max_files_per_sync": max_files,
        "gap_fill_max_files": gap_fill,
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
    """解析 TRI .dcl，返回单板头信息。

    兼容两种头：
    - 单行 CSV：PASS,...,barcode,YYYYMMDD,HHMMSS,...
    - 多行（ICT-115 常见）：PASS / … / board / barcode / YYYYMMDD / HHMMSS
    """
    text = _decode_dcl(data).replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        lines.append(s)
    barcode = ""
    result = "UNKNOWN"
    board_name = None
    ict_id = None
    tested_at = None
    if lines:
        first = lines[0]
        m = HEADER_RE.match(first)
        if m:
            result = _normalize_result(m.group(1))
            ict_id = (m.group(2) or "").strip() or None
            board_name = (m.group(4) or "").strip() or None
            barcode = (m.group(5) or "").strip()
            tested_at = _parse_tested_at(m.group(6), m.group(7))
        elif first.upper() in ("PASS", "FAIL") or first.upper().startswith("PASS") or first.upper().startswith("FAIL"):
            # 多行头：至少 PASS/FAIL + barcode + date + time
            result = _normalize_result(first.split(",", 1)[0])
            # 启发式：倒序找 YYYYMMDD + HHMMSS，再往前取条码/板名
            date_idx = None
            for i, s in enumerate(lines[1:], start=1):
                if re.fullmatch(r"\d{8}", s):
                    date_idx = i
                    break
            if date_idx is not None:
                date_s = lines[date_idx]
                time_s = lines[date_idx + 1] if date_idx + 1 < len(lines) else ""
                if re.fullmatch(r"\d{6}", time_s or ""):
                    tested_at = _parse_tested_at(date_s, time_s)
                # 日期前一行常为条码
                if date_idx >= 1:
                    barcode = lines[date_idx - 1].strip()
                # 再前一行常为板名/料号
                if date_idx >= 2:
                    board_name = lines[date_idx - 2].strip() or None
                if date_idx >= 3:
                    maybe_ict = lines[date_idx - 3].strip()
                    if maybe_ict.isdigit():
                        ict_id = maybe_ict
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


def _result_rank(result: Optional[str]) -> int:
    """结果优先级：PASS > UNKNOWN > FAIL。同条码复测有 PASS 时以 PASS 为准。"""
    from board_gate import is_fail, is_pass

    if is_pass(result):
        return 2
    if is_fail(result):
        return 0
    return 1


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
        # 合并规则：
        # 1) 双方都有 tested_at：较新者胜
        # 2) 新记录无时间、旧记录有时间：不覆盖（除非新结果是 PASS 且旧不是）
        # 3) 时间无法比较时：PASS 优先于 FAIL（复测通过不应被旧 FAIL 文件盖掉）
        old_t = row.tested_at
        new_t = payload.get("tested_at")
        old_rank = _result_rank(row.result)
        new_rank = _result_rank(payload.get("result"))
        if old_t and new_t:
            if new_t < old_t:
                if cache is not None:
                    cache[barcode] = row
                return
            if new_t == old_t and new_rank < old_rank:
                if cache is not None:
                    cache[barcode] = row
                return
        elif old_t and not new_t:
            # 新文件解析不出时间：仅允许 PASS 升级非 PASS
            if not (new_rank > old_rank):
                if cache is not None:
                    cache[barcode] = row
                return
        elif not old_t and not new_t:
            if new_rank < old_rank:
                if cache is not None:
                    cache[barcode] = row
                return
        # 已有 PASS 时，无更晚 tested_at 的 FAIL 不得回退
        if old_rank >= 2 and new_rank < 2:
            if not (new_t and old_t and new_t > old_t):
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
            # 恩玖 16 位：前 12 位 ∈ 已登记前缀；菲利斯：D0…
            # 用 substr（SQLite/Postgres 通用），勿用 left（仅 Postgres）
            q = q.filter(
                or_(
                    func.substr(IctBoardResult.barcode, 1, 12).in_(prefixes),
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


def _enumerate_dcl_via_win_unc(
    root: str,
    *,
    share_unc: str,
    user: str,
    pwd: str,
    thresh: float,
) -> tuple[list[tuple[str, float, int, str]], int, Optional[str]]:
    """Windows net use + os.scandir；适合 10 万级目录。返回 (candidates, skipped, err)。"""
    import os

    from smb_session import win_net_use, win_net_use_delete

    ok, msg = win_net_use(share_unc, user, pwd)
    if not ok:
        return [], 0, f"net use 失败: {msg}"
    raw: list[tuple[str, float, int, str]] = []
    skipped = 0
    try:
        for entry in os.scandir(root):
            name = entry.name
            if not name.lower().endswith(".dcl"):
                continue
            path = rf"{root}\{name}"
            try:
                st = entry.stat()
                mtime = float(st.st_mtime)
                size = int(st.st_size or 0)
            except Exception:
                continue
            if thresh > 0 and mtime < thresh:
                skipped += 1
                continue
            raw.append((name, mtime, size, path))
        return raw, skipped, None
    except Exception as e:
        return raw, skipped, str(e)
    finally:
        # 读文件仍走同一 UNC 会话；由调用方在整机同步结束再 delete
        pass


def _sync_one_machine(
    db: Session,
    machine: dict[str, Any],
    *,
    share: str,
    subpath: str,
    force_all: bool,
    max_files: int,
    lookback_days: int,
    gap_fill_max_files: int = 0,
) -> dict[str, Any]:
    from smbclient import open_file, scandir, stat
    from lan_host import resolve_machine_host
    from smb_session import (
        is_smb_conn_limit_error,
        smb_close_host,
        smb_register_with_retry,
        win_net_use_delete,
    )

    mid = (machine.get("id") or machine.get("host") or "ict").strip()
    host_cfg = (machine.get("host") or "").strip()
    host = resolve_machine_host(machine) or host_cfg
    user = (machine.get("username") or "Administrator").strip()
    pwd = machine.get("password") or ""
    share_unc = rf"\\{host}\{share}".rstrip("\\")
    root = rf"{share_unc}\{subpath}".rstrip("\\")
    out: dict[str, Any] = {
        "machine_id": mid,
        "host": host,
        "hostname": machine.get("hostname") or host_cfg,
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

    # 水位仅区分「新鲜增量」与「lookback 缺口」；枚举一律从 lookback floor 起，
    # 避免水位越过漏文件后永远不回扫（三防「未测ICT」根因）。
    last_mtime = (
        db.query(func.max(IctSyncFile.file_mtime))
        .filter(IctSyncFile.machine_id == mid)
        .scalar()
    )
    last_mtime_f = float(last_mtime or 0)
    floor = 0.0
    if lookback_days > 0 and not force_all:
        floor = time.time() - lookback_days * 86400
    if force_all or last_mtime_f <= 0:
        fresh_thresh = floor
    else:
        fresh_thresh = max(floor, last_mtime_f - _WATERMARK_OVERLAP_SEC)
    enum_thresh = floor
    out["mtime_thresh"] = enum_thresh
    out["fresh_thresh"] = fresh_thresh
    out["last_synced_mtime"] = last_mtime_f
    out["gap_fill_queued"] = 0
    out["gap_fill_processed"] = 0

    use_win_unc = False
    raw_entries: list[tuple[str, float, int, str]] = []
    list_err: Optional[str] = None

    # 优先 Windows UNC：ICT-119 上 smbprotocol 常在 ~2k 条后 socket closed，原生枚举可扫完 ~10 万
    win_raw, win_skipped, win_err = _enumerate_dcl_via_win_unc(
        root, share_unc=share_unc, user=user, pwd=pwd, thresh=enum_thresh
    )
    if win_err is None or win_raw:
        use_win_unc = True
        raw_entries = win_raw
        out["files_skipped"] += win_skipped
        out["enum_mode"] = "win_unc"
        _LOGIN_COOLDOWN_UNTIL.pop(mid, None)
        if win_err:
            out["errors"].append(f"win_unc列举中断(已保留{len(win_raw)}个候选): {win_err}")
    else:
        out["enum_mode"] = "smbprotocol"
        logger.warning("ICT %s win_unc 列举不可用，回退 smbprotocol: %s", mid, win_err)
        win_net_use_delete(share_unc)
        try:
            smb_register_with_retry(
                host,
                username=user,
                password=pwd,
                connection_timeout=20,
                encrypt=False,
                auth_protocol="ntlm",
            )
            _LOGIN_COOLDOWN_UNTIL.pop(mid, None)
        except Exception as e:
            msg = str(e)
            locked = (
                "0xc0000234" in msg.lower()
                or "locked" in msg.lower()
                or "0xc000006d" in msg.lower()
            )
            cool_sec = (
                20 * 60
                if locked or "logon" in msg.lower() or "authentication" in msg.lower()
                else 5 * 60
            )
            if is_smb_conn_limit_error(e):
                cool_sec = 60
            _LOGIN_COOLDOWN_UNTIL[mid] = now_ts + cool_sec
            out["errors"].append(f"登录失败: {e}（已冷却 {cool_sec // 60} 分钟）")
            smb_close_host(host)
            return out

        # 大目录 + SMB 易中途断连：重试；已扫到的候选不要丢弃
        for list_attempt in range(3):
            raw_entries = []
            skipped_this = 0
            try:
                for entry in scandir(root):
                    name = entry.name
                    if not name.lower().endswith(".dcl"):
                        continue
                    path = rf"{root}\{name}"
                    try:
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
                    if enum_thresh > 0 and mtime < enum_thresh:
                        skipped_this += 1
                        continue
                    raw_entries.append((name, mtime, size, path))
                out["files_skipped"] += skipped_this
                list_err = None
                break
            except Exception as e:
                list_err = str(e)
                out["files_skipped"] += skipped_this
                logger.warning(
                    "ICT %s 列举中断 attempt=%s skipped=%s candidates=%s err=%s",
                    mid,
                    list_attempt + 1,
                    skipped_this,
                    len(raw_entries),
                    e,
                )
                smb_close_host(host)
                if raw_entries:
                    out["errors"].append(f"列举中断(已保留{len(raw_entries)}个候选): {e}")
                    list_err = None
                    break
                try:
                    smb_register_with_retry(
                        host,
                        username=user,
                        password=pwd,
                        connection_timeout=20,
                        encrypt=False,
                        auth_protocol="ntlm",
                    )
                except Exception as re_e:
                    list_err = f"{e}; 重连失败: {re_e}"
                    low = str(re_e).lower()
                    if "logon" in low or "authentication" in low or "0xc000006d" in low:
                        _LOGIN_COOLDOWN_UNTIL[mid] = time.time() + 5 * 60
                    break
                time.sleep(1.5 * (list_attempt + 1))
        if list_err:
            out["errors"].append(f"列举失败: {list_err}")
            smb_close_host(host)
            return out

    # lookback 之外的直接跳过（双保险；主过滤已在枚举阶段）
    candidates: list[tuple[str, float, int, str]] = []
    for name, mtime, size, path in raw_entries:
        if floor > 0 and mtime < floor:
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

    gap_entries: list[tuple[str, float, int, str]] = []
    fresh_entries: list[tuple[str, float, int, str]] = []
    for name, mtime, size, path in candidates:
        prev = prev_meta.get(name)
        unchanged = (
            not force_all
            and prev
            and prev[0] is not None
            and abs(float(prev[0]) - mtime) < 0.5
            and prev[1] == size
        )
        if unchanged:
            out["files_skipped"] += 1
            continue
        # 从未进同步表且落在水位之下 → lookback 缺口，必须补
        if not force_all and prev is None and mtime < fresh_thresh:
            gap_entries.append((name, mtime, size, path))
            continue
        fresh_entries.append((name, mtime, size, path))

    gap_entries.sort(key=lambda x: x[1])  # 旧→新，先清历史漏抓
    fresh_entries.sort(key=lambda x: x[1], reverse=True)  # 新→旧
    out["gap_fill_queued"] = len(gap_entries)

    gap_quota = max(0, int(gap_fill_max_files or 0))
    if force_all:
        merged = gap_entries + fresh_entries
        entries = merged[:max_files] if max_files > 0 else merged
    else:
        if max_files > 0:
            gap_quota = min(gap_quota, max_files)
        gap_take = gap_entries[:gap_quota] if gap_quota > 0 else []
        if max_files <= 0:
            entries = gap_take + fresh_entries
        else:
            remain = max(0, max_files - len(gap_take))
            entries = gap_take + fresh_entries[:remain]
    gap_name_set = {n for n, _, _, _ in gap_entries[:gap_quota]} if gap_quota > 0 else set()
    out["gap_fill_processed"] = sum(1 for n, _, _, _ in entries if n in gap_name_set)

    out["files_seen"] = len(raw_entries)

    board_cache: dict[str, IctBoardResult] = {}
    for name, mtime, size, path in entries:
        try:
            if use_win_unc:
                with open(path, "rb") as f:
                    data = f.read()
            else:
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
    try:
        smb_close_host(host)
    except Exception:
        pass
    win_net_use_delete(share_unc)
    return out


def sync_ict_from_shares(db: Session, *, force_all: bool = False) -> dict[str, Any]:
    """抓取配置中全部 ICT 机台 .dcl 并入库。

    单机超时隔离：一台 SMB 卡死不再堵死整轮调度（配合 max_instances=1）。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    cfg = _ict_cfg()
    machines = cfg["machines"]
    if not machines:
        return {"status": "failed", "message": "未配置 ict.machines", "machines": []}
    results = []
    status_path = None
    try:
        from pathlib import Path

        status_path = Path(__file__).resolve().parent / "data" / "ict_sync_last.json"
        status_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        status_path = None

    for m in machines:
        mid = (m.get("id") or m.get("host") or "ict").strip()
        t0 = time.time()
        one: dict[str, Any]
        # 独立 Session，避免线程超时后污染主会话
        machine_db = SessionLocal()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(
                    _sync_one_machine,
                    machine_db,
                    m,
                    share=cfg["share"],
                    subpath=cfg["subpath"],
                    force_all=force_all,
                    max_files=cfg["max_files_per_sync"],
                    lookback_days=0 if force_all else cfg["lookback_days"],
                    gap_fill_max_files=0 if force_all else int(cfg.get("gap_fill_max_files") or 0),
                )
                try:
                    one = fut.result(timeout=_MACHINE_SYNC_TIMEOUT_SEC)
                    try:
                        machine_db.commit()
                    except Exception:
                        machine_db.rollback()
                except FuturesTimeout:
                    logger.error(
                        "ICT sync %s 超时 %ss，跳过本机继续下一台（防调度堵死）",
                        mid,
                        _MACHINE_SYNC_TIMEOUT_SEC,
                    )
                    try:
                        machine_db.rollback()
                    except Exception:
                        pass
                    one = {
                        "machine_id": mid,
                        "host": m.get("host"),
                        "files_seen": 0,
                        "files_processed": 0,
                        "files_skipped": 0,
                        "boards_upserted": 0,
                        "errors": [f"timeout {_MACHINE_SYNC_TIMEOUT_SEC}s"],
                        "elapsed_sec": _MACHINE_SYNC_TIMEOUT_SEC,
                    }
        except Exception as e:
            logger.exception("ICT sync %s 异常", mid)
            try:
                machine_db.rollback()
            except Exception:
                pass
            one = {
                "machine_id": mid,
                "files_seen": 0,
                "files_processed": 0,
                "files_skipped": 0,
                "boards_upserted": 0,
                "errors": [str(e)],
            }
        finally:
            try:
                machine_db.close()
            except Exception:
                pass

        one["elapsed_sec"] = round(time.time() - t0, 1)
        results.append(one)
        errs = one.get("errors") or []
        if errs:
            logger.warning(
                "ICT sync %s processed=%s upserted=%s elapsed=%ss errors=%s sample=%s",
                one.get("machine_id"),
                one.get("files_processed"),
                one.get("boards_upserted"),
                one.get("elapsed_sec"),
                len(errs),
                errs[0],
            )
        else:
            logger.info(
                "ICT sync %s processed=%s upserted=%s elapsed=%ss errors=0",
                one.get("machine_id"),
                one.get("files_processed"),
                one.get("boards_upserted"),
                one.get("elapsed_sec"),
            )

    summary = {
        "status": "ok",
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "machines": results,
        "boards_upserted": sum(int(r.get("boards_upserted") or 0) for r in results),
        "files_processed": sum(int(r.get("files_processed") or 0) for r in results),
    }
    if status_path is not None:
        try:
            import json

            status_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("写入 ict_sync_last.json 失败")
    return summary


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
