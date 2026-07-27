"""恩玖测试日志同步（156 本机 ENJOY）→ ict_board_results。

来源：
- ATS/log/Var_Type：JSON
- DigiTest/log：日期/机型/*.log（GBK）

扫码只查库；本模块仅后台拉取，不在现场扫盘。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import load_config
from ict_sync import _upsert_board
from models import IctSyncFile

logger = logging.getLogger(__name__)

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
JSON_RE = re.compile(r"\.json$", re.I)
LOG_RE = re.compile(r"\.log$", re.I)
_SN_IN_NAME = re.compile(r"\((\d{16})(?:-\d+)?\)")
_DIGITEST_FAIL_RE = re.compile(r"Result\[Success\d*;\s*Fail:(\d+)\]", re.I)
_DIGITEST_SN_RE = re.compile(r"PCBA(?:序号|条码|编码)[:：]\s*(\d{16})")
_DIGITEST_DT_RE = re.compile(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_DIGITEST_BOX_RE = re.compile(r"(?:测试架|测试集)[:：]\s*(\S+)")

_LOGIN_COOLDOWN_UNTIL: dict[str, float] = {}
_LAST_ATS_SYNC_AT: float = 0.0


def _ats_cfg() -> dict[str, Any]:
    cfg = load_config()
    raw = cfg.get("enjiu_ats") or {}
    machines = list(raw.get("machines") or [])
    share = (raw.get("share") or "ENJOY").strip()
    # sources：优先显式配置；否则用 machines × 默认两目录
    sources = list(raw.get("sources") or [])
    if not sources and machines:
        m0 = machines[0]
        host = (m0.get("host") or "").strip()
        user = (m0.get("username") or "Administrator").strip()
        pwd = m0.get("password") or ""
        sources = [
            {
                "id": (m0.get("id") or "enjiu-ats-156").strip(),
                "host": host,
                "username": user,
                "password": pwd,
                "share": share,
                "subpath": (raw.get("subpath") or "ATS/log/Var_Type").strip(),
                "kind": "var_type_json",
            },
            {
                "id": "enjiu-digitest-156",
                "host": host,
                "username": user,
                "password": pwd,
                "share": share,
                "subpath": "DigiTest/log",
                "kind": "digitest_log",
            },
        ]
    for s in sources:
        s["subpath"] = (s.get("subpath") or "").strip().replace("/", "\\")
        s["share"] = (s.get("share") or share).strip()
        s["kind"] = (s.get("kind") or "var_type_json").strip()
    return {
        "auto_sync_enabled": bool(raw.get("auto_sync_enabled", False)),
        # 时间窗仍跟菲利斯；回溯以在制单为主，默认 120 天（非菲利斯的 7 天）
        "open_orders_only": bool(raw.get("open_orders_only", True)),
        "lookback_days": int(raw.get("lookback_days") or 120),
        "max_files_per_sync": int(raw.get("max_files_per_sync") or 2000),
        "share": share,
        "sources": sources,
        "machines": machines,
    }


def should_run_enjiu_ats_sync() -> tuple[bool, str]:
    """与菲利斯共用 ict.sync_windows，独立记录上次运行（调度错开用）。"""
    from ict_sync import should_run_sync_windows

    ict = load_config().get("ict") or {}
    return should_run_sync_windows(ict, _LAST_ATS_SYNC_AT, skip_label="恩玖ATS同步")


def mark_enjiu_ats_sync_ran() -> None:
    global _LAST_ATS_SYNC_AT
    _LAST_ATS_SYNC_AT = time.time()


def open_enjiu_barcode_prefixes(db: Session) -> set[str]:
    """在制恩玖订单在贴码登记中的 barcode_prefix 集合。"""
    from models import LaserBatch, SrmOrder

    open_pos = [
        pn
        for (pn,) in db.query(SrmOrder.purchase_no)
        .filter(
            SrmOrder.customer_id.in_(("enjiu", "a116")),
            SrmOrder.is_completed.is_(False),
            SrmOrder.purchase_no.isnot(None),
            SrmOrder.purchase_no != "",
        )
        .distinct()
        .all()
        if (pn or "").strip()
    ]
    if not open_pos:
        return set()
    rows = (
        db.query(LaserBatch.barcode_prefix)
        .filter(
            LaserBatch.customer_id.in_(("enjiu", "a116")),
            LaserBatch.purchase_no.in_(open_pos),
            LaserBatch.barcode_prefix.isnot(None),
            LaserBatch.barcode_prefix != "",
        )
        .distinct()
        .all()
    )
    return {(p or "").strip() for (p,) in rows if (p or "").strip()}


def _normalize_result(raw: Optional[str]) -> str:
    t = (raw or "").strip()
    if not t:
        return "UNKNOWN"
    u = t.upper()
    if u in ("SUCCESS", "PASS", "OK", "P"):
        return "PASS"
    if u in ("FAIL", "FAILED", "NG", "FALL"):
        return "FAIL"
    if "FAIL" in u or "NG" in u:
        return "FAIL"
    if "SUCCESS" in u or u.startswith("P"):
        return "PASS"
    return u[:16]


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    cleaned = text.replace("T", " ").replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H-%M-%S"):
        try:
            return datetime.strptime(cleaned[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _load_json_bytes(data: bytes) -> dict[str, Any]:
    last_err: Optional[Exception] = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"):
        try:
            return json.loads(data.decode(enc))
        except Exception as e:
            last_err = e
            continue
    raise ValueError(f"JSON 解码失败: {last_err}")


def parse_ats_json(data: dict[str, Any], *, filename: str = "") -> Optional[dict[str, Any]]:
    """解析单份 ATS Var_Type JSON → ICT upsert payload。"""
    vars_list = data.get("Variable") or data.get("variable") or []
    var_map: dict[str, str] = {}
    if isinstance(vars_list, list):
        for item in vars_list:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            var_map[name] = str(item.get("value") if item.get("value") is not None else "").strip()

    barcode = (
        str(data.get("BoardSN") or data.get("boardSN") or "").strip()
        or var_map.get("Board_Key", "").strip()
        or var_map.get("BoardKey", "").strip()
    )
    barcode = re.sub(r"\s+", "", barcode)
    if not barcode or barcode.upper() in ("NULL", "NONE", "N/A", "-", "—"):
        return None
    # 文件名兜底：...(0290741126280032-474).json
    if not re.fullmatch(r"\d{16}", barcode) and filename:
        m = re.search(r"\((\d{16})(?:-\d+)?\)", filename)
        if m:
            barcode = m.group(1)

    result = _normalize_result(str(data.get("Result") or data.get("result") or ""))
    tested_at = _parse_dt(str(data.get("EndTime") or "")) or _parse_dt(str(data.get("StartTime") or ""))
    board_name = var_map.get("BOX_Name") or var_map.get("Box_Name") or None
    from pcba_barcode import parse_pcba_barcode

    parsed = parse_pcba_barcode(barcode)
    code = parsed["barcode"] if parsed else barcode
    return {
        "barcode": code,
        "board_name": board_name,
        "result": result,
        "tested_at": tested_at,
        "model_mid": parsed.get("model_mid") if parsed else None,
        "model_ver": parsed.get("model_ver") if parsed else None,
        "laser_date": parsed.get("laser_date") if parsed else None,
        "seq": parsed.get("seq") if parsed else None,
        "model_code": (parsed.get("model_code_guess") if parsed else None) or board_name,
        "ict_id": None,
    }


def parse_digitest_log(raw: bytes, *, filename: str = "", box_name: str = "") -> Optional[dict[str, Any]]:
    """解析 DigiTest .log 头信息 → ICT upsert payload。Fail:0 为 PASS。"""
    text = raw.decode("gbk", errors="replace")
    head = text[:4000]
    barcode = ""
    m_sn = _DIGITEST_SN_RE.search(head)
    if m_sn:
        barcode = m_sn.group(1)
    if not barcode and filename:
        m = _SN_IN_NAME.search(filename)
        if m:
            barcode = m.group(1)
    barcode = re.sub(r"\s+", "", barcode or "")
    if not barcode or barcode in ("000", "0") or not re.fullmatch(r"\d{16}", barcode):
        return None

    fail_n = None
    m_fail = _DIGITEST_FAIL_RE.search(head)
    if m_fail:
        fail_n = int(m_fail.group(1))
    result = "PASS" if fail_n == 0 else ("FAIL" if fail_n is not None else "UNKNOWN")

    times = _DIGITEST_DT_RE.findall(head)
    tested_at = _parse_dt(times[1] if len(times) >= 2 else (times[0] if times else None))
    box = box_name
    if not box:
        m_box = _DIGITEST_BOX_RE.search(head)
        if m_box:
            box = m_box.group(1)

    from pcba_barcode import parse_pcba_barcode

    parsed = parse_pcba_barcode(barcode)
    code = parsed["barcode"] if parsed else barcode
    return {
        "barcode": code,
        "board_name": box or None,
        "result": result,
        "tested_at": tested_at,
        "model_mid": parsed.get("model_mid") if parsed else None,
        "model_ver": parsed.get("model_ver") if parsed else None,
        "laser_date": parsed.get("laser_date") if parsed else None,
        "seq": parsed.get("seq") if parsed else None,
        "model_code": (parsed.get("model_code_guess") if parsed else None) or box,
        "ict_id": None,
    }


def _collect_var_type_candidates(
    *,
    root: str,
    day_names: list[str],
    prefix_allowlist: Optional[set[str]],
    prev_meta: dict,
    force_all: bool,
    out: dict[str, Any],
    scandir,
) -> list[tuple[str, float, int, str]]:
    """返回 (key, mtime, size, path)。"""
    candidates: list[tuple[str, float, int, str]] = []
    for day in day_names:
        day_path = rf"{root}\{day}"
        try:
            entries = list(scandir(day_path))
        except Exception as e:
            out["errors"].append(f"{day}: {e}")
            continue
        for e in entries:
            if not e.is_file() or not JSON_RE.search(e.name):
                continue
            if prefix_allowlist is not None:
                m = _SN_IN_NAME.search(e.name)
                if not m or m.group(1)[:12] not in prefix_allowlist:
                    out["files_filtered"] += 1
                    continue
            try:
                st = e.stat()
                mtime = float(st.st_mtime or 0)
                size = int(st.st_size or 0)
            except Exception:
                continue
            key = f"{day}/{e.name}"
            out["files_seen"] += 1
            old = prev_meta.get(key)
            if not force_all and old and old[0] == mtime and old[1] == size:
                out["files_skipped"] += 1
                continue
            candidates.append((key, mtime, size, rf"{day_path}\{e.name}"))
    return candidates


def _collect_digitest_candidates(
    *,
    root: str,
    day_names: list[str],
    prefix_allowlist: Optional[set[str]],
    prev_meta: dict,
    force_all: bool,
    out: dict[str, Any],
    scandir,
    listdir,
) -> list[tuple[str, float, int, str, str]]:
    """返回 (key, mtime, size, path, box_name)。"""
    candidates: list[tuple[str, float, int, str, str]] = []
    for day in day_names:
        day_path = rf"{root}\{day}"
        try:
            prog_names = [n for n in listdir(day_path) if n and n not in (".", "..")]
        except Exception as e:
            out["errors"].append(f"{day}: {e}")
            continue
        for prog in prog_names:
            prog_path = rf"{day_path}\{prog}"
            try:
                entries = list(scandir(prog_path))
            except Exception:
                # 也可能文件直接在日期目录
                continue
            for e in entries:
                if not e.is_file() or not LOG_RE.search(e.name):
                    continue
                if prefix_allowlist is not None:
                    m = _SN_IN_NAME.search(e.name)
                    if not m or m.group(1)[:12] not in prefix_allowlist:
                        out["files_filtered"] += 1
                        continue
                try:
                    st = e.stat()
                    mtime = float(st.st_mtime or 0)
                    size = int(st.st_size or 0)
                except Exception:
                    continue
                key = f"{day}/{prog}/{e.name}"
                out["files_seen"] += 1
                old = prev_meta.get(key)
                if not force_all and old and old[0] == mtime and old[1] == size:
                    out["files_skipped"] += 1
                    continue
                candidates.append((key, mtime, size, rf"{prog_path}\{e.name}", prog))
    return candidates


def _sync_one_source(
    db: Session,
    source: dict[str, Any],
    *,
    force_all: bool,
    max_files: int,
    lookback_days: int,
    prefix_allowlist: Optional[set[str]] = None,
) -> dict[str, Any]:
    from smbclient import open_file, register_session, reset_connection_cache, scandir, listdir

    mid = (source.get("id") or source.get("host") or "enjiu-ats").strip()
    host = (source.get("host") or "").strip()
    user = (source.get("username") or "Administrator").strip()
    pwd = source.get("password") or ""
    share = (source.get("share") or "ENJOY").strip()
    subpath = (source.get("subpath") or "").strip().rstrip("\\")
    kind = (source.get("kind") or "var_type_json").strip()
    root = rf"\\{host}\{share}\{subpath}".rstrip("\\")
    out: dict[str, Any] = {
        "machine_id": mid,
        "host": host,
        "share": root,
        "kind": kind,
        "files_seen": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "files_filtered": 0,
        "boards_upserted": 0,
        "open_prefixes": len(prefix_allowlist or []),
        "errors": [],
    }
    if not host:
        out["errors"].append("缺少 host")
        return out

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
        locked = "0xc0000234" in msg.lower() or "locked" in msg.lower() or "0xc000006d" in msg.lower()
        cool_sec = 20 * 60 if locked or "logon" in msg.lower() or "authentication" in msg.lower() else 5 * 60
        _LOGIN_COOLDOWN_UNTIL[mid] = now_ts + cool_sec
        out["errors"].append(f"登录失败: {e}（已冷却 {cool_sec // 60} 分钟）")
        return out

    try:
        day_names = [d for d in listdir(root) if DAY_RE.match(d)]
    except Exception as e:
        out["errors"].append(f"无法列出目录: {e}")
        return out

    day_names.sort(reverse=True)
    if lookback_days > 0 and not force_all:
        cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        day_names = [d for d in day_names if d >= cutoff]

    prev_rows = (
        db.query(IctSyncFile.filename, IctSyncFile.file_mtime, IctSyncFile.file_size)
        .filter(IctSyncFile.machine_id == mid)
        .all()
    )
    prev_meta = {fn: (mt, sz) for fn, mt, sz in prev_rows}

    board_cache: dict = {}
    if kind == "digitest_log":
        raw_cands = _collect_digitest_candidates(
            root=root,
            day_names=day_names,
            prefix_allowlist=prefix_allowlist,
            prev_meta=prev_meta,
            force_all=force_all,
            out=out,
            scandir=scandir,
            listdir=listdir,
        )
        raw_cands.sort(key=lambda x: -x[1])
        if max_files > 0:
            raw_cands = raw_cands[:max_files]
        for key, mtime, size, path, box in raw_cands:
            try:
                # 头信息足够判定条码/结果，大文件不必全读
                with open_file(path, mode="rb") as f:
                    raw = f.read(8192)
                fname = key.rsplit("/", 1)[-1]
                parsed = parse_digitest_log(raw, filename=fname, box_name=box)
                count = 0
                if parsed:
                    if prefix_allowlist is not None and (parsed["barcode"] or "")[:12] not in prefix_allowlist:
                        out["files_filtered"] += 1
                    else:
                        parsed["source_file"] = key
                        parsed["source_host"] = host
                        parsed["machine_id"] = mid
                        _upsert_board(db, parsed, board_cache)
                        count = 1
                        out["boards_upserted"] += 1
                prev_row = (
                    db.query(IctSyncFile)
                    .filter(IctSyncFile.machine_id == mid, IctSyncFile.filename == key)
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
                            filename=key,
                            file_mtime=mtime,
                            file_size=size,
                            row_count=count,
                            processed_at=now,
                        )
                    )
                out["files_processed"] += 1
                if out["files_processed"] % 200 == 0:
                    db.commit()
            except Exception as e:
                logger.exception("恩玖 DigiTest 处理失败 %s %s", mid, key)
                try:
                    db.rollback()
                except Exception:
                    pass
                board_cache.clear()
                out["errors"].append(f"{key}: {e}")
                if len(out["errors"]) >= 20:
                    break
    else:
        candidates = _collect_var_type_candidates(
            root=root,
            day_names=day_names,
            prefix_allowlist=prefix_allowlist,
            prev_meta=prev_meta,
            force_all=force_all,
            out=out,
            scandir=scandir,
        )
        candidates.sort(key=lambda x: -x[1])
        if max_files > 0:
            candidates = candidates[:max_files]
        for key, mtime, size, path in candidates:
            try:
                with open_file(path, mode="rb") as f:
                    raw = f.read()
                data = _load_json_bytes(raw)
                name = key.rsplit("/", 1)[-1]
                parsed = parse_ats_json(data, filename=name)
                count = 0
                if parsed:
                    if prefix_allowlist is not None and (parsed["barcode"] or "")[:12] not in prefix_allowlist:
                        out["files_filtered"] += 1
                    else:
                        parsed["source_file"] = key
                        parsed["source_host"] = host
                        parsed["machine_id"] = mid
                        _upsert_board(db, parsed, board_cache)
                        count = 1
                        out["boards_upserted"] += 1
                prev_row = (
                    db.query(IctSyncFile)
                    .filter(IctSyncFile.machine_id == mid, IctSyncFile.filename == key)
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
                            filename=key,
                            file_mtime=mtime,
                            file_size=size,
                            row_count=count,
                            processed_at=now,
                        )
                    )
                out["files_processed"] += 1
                if out["files_processed"] % 200 == 0:
                    db.commit()
            except Exception as e:
                logger.exception("恩玖 ATS 文件处理失败 %s %s", mid, key)
                try:
                    db.rollback()
                except Exception:
                    pass
                board_cache.clear()
                out["errors"].append(f"{key}: {e}")
                if len(out["errors"]) >= 20:
                    break
    try:
        db.commit()
    except Exception as e:
        logger.exception("恩玖测试同步提交失败 %s", mid)
        db.rollback()
        out["errors"].append(f"commit: {e}")
    return out


def sync_enjiu_ats_from_shares(
    db: Session,
    *,
    force_all: bool = False,
    open_orders_only: Optional[bool] = None,
) -> dict[str, Any]:
    """从 156 本机 ENJOY 抓取 ATS JSON + DigiTest log → ict_board_results。

    默认只同步「系统在制恩玖订单」贴码前缀对应的测试，不灌全盘历史。
    """
    cfg = _ats_cfg()
    sources = cfg["sources"]
    if not sources:
        return {"status": "failed", "message": "未配置 enjiu_ats.sources/machines", "machines": []}

    only_open = cfg["open_orders_only"] if open_orders_only is None else bool(open_orders_only)
    prefixes: Optional[set[str]] = None
    if only_open:
        prefixes = open_enjiu_barcode_prefixes(db)
        if not prefixes:
            return {
                "status": "ok",
                "message": "无在制恩玖贴码前缀，跳过",
                "machines": [],
                "boards_upserted": 0,
                "files_processed": 0,
                "open_prefixes": 0,
            }

    # 单次上限在多来源间均分，避免一轮过长
    per_source = max(200, cfg["max_files_per_sync"] // max(1, len(sources)))
    results = []
    for src in sources:
        one = _sync_one_source(
            db,
            src,
            force_all=force_all,
            max_files=per_source,
            lookback_days=0 if force_all else cfg["lookback_days"],
            prefix_allowlist=prefixes,
        )
        results.append(one)
        errs = one.get("errors") or []
        if errs:
            logger.warning(
                "Enjiu test sync %s kind=%s processed=%s upserted=%s filtered=%s errors=%s sample=%s",
                one.get("machine_id"),
                one.get("kind"),
                one.get("files_processed"),
                one.get("boards_upserted"),
                one.get("files_filtered"),
                len(errs),
                errs[0],
            )
        else:
            logger.info(
                "Enjiu test sync %s kind=%s processed=%s upserted=%s filtered=%s errors=0",
                one.get("machine_id"),
                one.get("kind"),
                one.get("files_processed"),
                one.get("boards_upserted"),
                one.get("files_filtered"),
            )
    return {
        "status": "ok",
        "open_orders_only": only_open,
        "open_prefixes": len(prefixes or []),
        "machines": results,
        "boards_upserted": sum(int(r.get("boards_upserted") or 0) for r in results),
        "files_processed": sum(int(r.get("files_processed") or 0) for r in results),
    }
