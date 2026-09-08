"""炉前 AOI：从 mes_data 共享盘抓取 CSV，按镭雕挂采购单。

独立表 pre_oven_aoi_board_results，只读展示，不写入 aoi_board_results，
不影响 SMT-AOI 扫码卡控 / board_gate / 包装扫码。
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import load_config
from database import SessionLocal
from laser_service import find_laser_batch_for_barcode
from models import PreOvenAoiBoardResult, PreOvenAoiSyncFile
from pcba_barcode import parse_pcba_barcode

logger = logging.getLogger(__name__)

MACHINE_ID = "pre-oven-aoi"
_WATERMARK_OVERLAP_SEC = 7200
# 20260813175928_D02002350926072688789_1_NG.csv
_FNAME = re.compile(
    r"^(?P<ts>\d{14})_(?P<barcode>[A-Za-z0-9]*)_(?P<idx>\d+)_(?P<res>NG|PASS|REPASS)\.csv$",
    re.IGNORECASE,
)


def _pre_oven_cfg() -> dict[str, Any]:
    """炉前 AOI 配置：支持 machines[] 多机（与 SMT-AOI 类似），兼容旧单机 host/share。"""
    cfg = load_config()
    raw = cfg.get("pre_oven_aoi") or {}
    share = (raw.get("share") or "mes_data").strip() or "mes_data"
    username = (raw.get("username") or "emsdata").strip() or "emsdata"
    password = raw.get("password") if raw.get("password") is not None else ""
    max_files = int(raw.get("max_files_per_sync") or 0)
    lookback_days = int(raw.get("lookback_days") or 30)

    machines = raw.get("machines")
    if isinstance(machines, list) and machines:
        out_machines: list[dict[str, Any]] = []
        for m in machines:
            if not isinstance(m, dict):
                continue
            host = (m.get("host") or "").strip()
            if not host:
                continue
            mid = (m.get("id") or f"pre-oven-{host.split('.')[-1]}").strip()
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
            return {
                "machines": out_machines,
                "max_files": max_files,
                "lookback_days": lookback_days,
            }

    host = (raw.get("host") or "192.168.2.138").strip()
    mid = (raw.get("id") or MACHINE_ID).strip() or MACHINE_ID
    return {
        "machines": [
            {
                "id": mid,
                "host": host,
                "share": share,
                "username": username,
                "password": password,
            }
        ],
        "max_files": max_files,
        "lookback_days": lookback_days,
    }


def _share_root(machine: dict[str, Any]) -> str:
    return rf"\\{machine['host']}\{machine['share']}"


def _map_result(token: str) -> str:
    t = (token or "").strip().upper()
    if t in ("PASS", "REPASS", "OK"):
        return "PASS"
    if t in ("NG", "FAIL", "FALL"):
        return "FAIL"
    return "UNKNOWN"


def _parse_tested_at(raw: str) -> Optional[datetime]:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text[:19] if len(text) >= 19 and fmt.startswith("%Y/") else text[:14], fmt)
        except ValueError:
            continue
    return None


def _ts_from_filename(ts: str) -> Optional[datetime]:
    try:
        return datetime.strptime(ts, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _read_text(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gbk", "gb18030", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _meta_from_csv(text: str) -> dict[str, str]:
    """解析炉前 AOI 键值头：拼板条码 / 测试时间 / 面别 / 程序名。"""
    out: dict[str, str] = {}
    try:
        reader = csv.reader(io.StringIO(text))
        for i, row in enumerate(reader):
            if i > 40:
                break
            if not row:
                continue
            key = (row[0] or "").strip()
            val = (row[1] or "").strip() if len(row) > 1 else ""
            if not key:
                continue
            if key in ("拼板条码", "整板条码", "条码"):
                if val:
                    out["barcode"] = val
            elif key in ("测试时间", "检测时间"):
                if val:
                    out["tested_at"] = val
            elif key in ("面别", "面"):
                if val:
                    out["side"] = val
            elif key.startswith("程序"):
                if val:
                    out["program"] = val
            elif key in ("设备名称", "机器"):
                if val:
                    out["machine"] = val
            elif "最终结" in key or key in ("整板最终结果", "拼板最终结果"):
                if val:
                    out["result"] = val
    except Exception:
        pass
    return out


def _fail_summary_from_csv(text: str) -> Optional[str]:
    """从器件明细表提取 NG 摘要，如 15:jack wrongPart|Missing。"""
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except Exception:
        return None
    header_idx: Optional[int] = None
    col_map: dict[str, int] = {}
    for i, row in enumerate(rows):
        if not row:
            continue
        joined = "".join((c or "") for c in row)
        if "器件位号" not in joined:
            continue
        header_idx = i
        for j, h in enumerate(row):
            key = (h or "").strip()
            if key:
                col_map[key] = j
        break
    if header_idx is None:
        return None

    res_col = col_map.get("器件复判结果")
    if res_col is None:
        for k, j in col_map.items():
            if "复判结果" in k:
                res_col = j
                break
    if res_col is None:
        res_col = col_map.get("器件检测结果")
    ref_col = col_map.get("器件位号", 0)
    type_col = col_map.get("器件类型")

    parts: list[str] = []
    for row in rows[header_idx + 1 :]:
        if not row or not any((c or "").strip() for c in row):
            continue
        if ref_col >= len(row):
            continue
        ref = (row[ref_col] or "").strip()
        if not ref:
            continue
        res = (row[res_col] or "").strip() if res_col is not None and res_col < len(row) else ""
        if not res or res.upper() == "OK":
            continue
        typ = ""
        if type_col is not None and type_col < len(row):
            typ = (row[type_col] or "").strip()
        if typ:
            parts.append(f"{ref}:{typ} {res}")
        else:
            parts.append(f"{ref}:{res}")
    if not parts:
        return None
    summary = "; ".join(parts)
    return summary[:2000]


# 炉前 AOI 机器码 → 中文（只用于展示，不参与扫码卡控）
_PRE_OVEN_PART_ZH: dict[str, str] = {
    "wrongpart": "错件",
    "missing": "缺件",
    "wrongpart|missing": "错件/缺件",
    "wrongpartormissing": "错件/缺件",
    "polarity": "极性反",
    "reverse": "极性反",
    "skew": "偏移",
    "offset": "偏移",
    "lift": "翘脚",
    "tombstone": "立碑",
    "bridge": "连锡",
    "short": "短路",
    "opensolder": "开焊",
    "insufficient": "少锡",
    "excess": "多锡",
    "solder": "焊接不良",
    "damage": "破损",
    "ocr": "条码/OCR",
    "foreign": "异物",
    "dirty": "脏污",
    "coplanarity": "共面度",
    "height": "高度",
    "area": "面积",
    "color": "颜色",
    "pattern": "形态",
}

_PRE_OVEN_TYPE_ZH: dict[str, str] = {
    "jack": "插座",
    "jack_black": "黑色插座",
    "jack_grid": "网格插座",
    "jack_convex": "凸点插座",
    "fourcorner_terminal": "四角端子",
    "other": "其它",
    "pp_capa": "贴片电容",
    "qr_code": "二维码",
    "mark": "Mark点",
}

# 机台器件类型 → 标准位号字母前缀（机台 CSV 器件位号常为纯数字）
_PRE_OVEN_TYPE_PREFIX: dict[str, str] = {
    "jack": "J",
    "jack_black": "J",
    "jack_grid": "J",
    "jack_convex": "J",
    "fourcorner_terminal": "J",
    "pp_capa": "C",
    "qr_code": "QR",
    "mark": "MK",
}

_REFDES_SUFFIX_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def _defect_token_zh(token: str) -> str:
    key = (token or "").strip().lower().replace("or", "|")
    if not key:
        return ""
    if key in _PRE_OVEN_PART_ZH:
        return _PRE_OVEN_PART_ZH[key]
    bits = [b.strip() for b in re.split(r"[|/]", key) if b.strip()]
    if len(bits) > 1:
        mapped = [_defect_token_zh(b) for b in bits]
        if all(m for m in mapped):
            return "/".join(dict.fromkeys(mapped))
    return _PRE_OVEN_PART_ZH.get(key, token.strip())


def _part_type_zh(part_type: str) -> str:
    key = (part_type or "").strip().lower()
    if not key:
        return ""
    return _PRE_OVEN_TYPE_ZH.get(key, part_type.strip())


def build_pre_oven_refdes_suffix_map(db: Session, model_code: str) -> dict[str, str]:
    """机型 BOM/坐标：数字后缀 → 完整位号，如 18→J18、110→C110（只读展示）。"""
    from engineering_service import normalize_code
    from models import BomLine, BomModel, PcbPlacementFile, PcbPlacementLine
    from mount_classification import split_refdes

    mc = normalize_code(model_code)
    if not mc:
        return {}
    out: dict[str, str] = {}

    def _add(refdes: str) -> None:
        rd = (refdes or "").strip().upper()
        if not rd:
            return
        m = _REFDES_SUFFIX_RE.match(rd)
        if not m:
            return
        suffix = m.group(2)
        if suffix not in out:
            out[suffix] = rd

    bom_ids = [
        b.id
        for b in db.query(BomModel).filter(BomModel.is_active.is_(True)).all()
        if normalize_code(b.model_code) == mc
    ]
    if bom_ids:
        for (pos,) in (
            db.query(BomLine.position)
            .filter(BomLine.bom_model_id.in_(bom_ids), BomLine.is_active.is_(True))
            .all()
        ):
            for rd in split_refdes(pos):
                _add(rd)

    pf_ids = [
        pf.id
        for pf in db.query(PcbPlacementFile).filter(PcbPlacementFile.model_code != "").all()
        if normalize_code(pf.model_code) == mc
    ]
    if pf_ids:
        for (rd,) in (
            db.query(PcbPlacementLine.refdes)
            .filter(
                PcbPlacementLine.placement_file_id.in_(pf_ids),
                PcbPlacementLine.skip.is_(False),
            )
            .all()
        ):
            _add(rd)
    return out


def format_pre_oven_ref(
    ref: str,
    part_type: str = "",
    *,
    suffix_map: Optional[dict[str, str]] = None,
) -> str:
    """机台纯数字位号 → 标准位号（J18/C110）；已有字母则原样返回。"""
    raw = (ref or "").strip()
    if not raw:
        return ""
    if _REFDES_SUFFIX_RE.match(raw):
        return raw.upper()
    typ = (part_type or "").strip().lower()
    type_prefix = _PRE_OVEN_TYPE_PREFIX.get(typ, "")
    if raw.isdigit():
        # 机台有器件类型时优先 J/C 等前缀，避免 BOM 数字后缀歧义（如 11→J11 而非 C11）
        if type_prefix:
            return f"{type_prefix}{raw}"
        mapped = (suffix_map or {}).get(raw)
        if mapped:
            return mapped.upper()
    return raw.upper()


def format_pre_oven_fail_summary(
    raw: Optional[str],
    *,
    model_code: str = "",
    suffix_map: Optional[dict[str, str]] = None,
    db: Optional[Session] = None,
) -> str:
    """机器摘要转中文，如 106:other wrongPart|Missing → U106（其它）错件/缺件。"""
    text = (raw or "").strip()
    if not text:
        return ""
    sm = suffix_map
    if sm is None and db is not None and (model_code or "").strip():
        sm = build_pre_oven_refdes_suffix_map(db, model_code)
    out: list[str] = []
    for seg in text.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(r"^(\d+):(\S+)\s+(.+)$", seg)
        if m:
            ref, typ, defect = m.group(1), m.group(2), m.group(3)
            typ_zh = _part_type_zh(typ)
            defect_zh = _defect_token_zh(defect)
            ref_disp = format_pre_oven_ref(ref, typ, suffix_map=sm)
            if typ_zh:
                out.append(f"{ref_disp}（{typ_zh}）{defect_zh}")
            else:
                out.append(f"{ref_disp} {defect_zh}")
            continue
        m2 = re.match(r"^(\d+):(.+)$", seg)
        if m2:
            ref, defect = m2.group(1), m2.group(2)
            ref_disp = format_pre_oven_ref(ref, "", suffix_map=sm)
            out.append(f"{ref_disp} {_defect_token_zh(defect)}")
            continue
        out.append(seg)
    return "；".join(out)


def _parse_fail_segments(fail_summary: Optional[str]) -> list[tuple[str, str, str]]:
    """解析存储摘要 → [(位号, 器件类型, 不良原码), ...]"""
    text = (fail_summary or "").strip()
    if not text:
        return []
    out: list[tuple[str, str, str]] = []
    for seg in text.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(r"^(\d+):(\S+)\s+(.+)$", seg)
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
            continue
        m2 = re.match(r"^(\d+):(.+)$", seg)
        if m2:
            out.append((m2.group(1), "", m2.group(2)))
    return out


def _defect_phenomena_count(defect_raw: str) -> int:
    """同一器件上几种不良现象（wrongPart|Missing 算 2 种）。"""
    raw = (defect_raw or "").strip()
    if not raw:
        return 0
    parts = re.split(r"[|/]", raw.replace("OR", "|").replace("or", "|"))
    parts = [p.strip() for p in parts if p.strip() and p.strip().upper() != "OK"]
    return len(parts) if parts else 0


def pre_oven_ng_item_count(fail_summary: Optional[str]) -> int:
    """不良位号条数。"""
    return len(_parse_fail_segments(fail_summary))


def pre_oven_fail_kind(*, result: Optional[str], fail_summary: Optional[str]) -> str:
    """
    炉前 AOI 判定（后焊卡控）：
    - 真不良：仅 1 个位号，且仅 1 种不良现象（不含错件+缺件同现）
    - 误报：≥2 个位号，或 wrongPart|Missing 等组合不良
    """
    ru = (result or "").strip().upper()
    if ru in ("PASS", "OK", "REPASS", "SUCCESS") or (ru.startswith("P") and "FAIL" not in ru):
        return "pass"
    if ru not in ("FAIL", "FALL", "NG") and "FAIL" not in ru and "NG" not in ru:
        return "unknown"
    segs = _parse_fail_segments(fail_summary)
    if len(segs) >= 2:
        return "false_positive"
    if len(segs) == 1:
        if _defect_phenomena_count(segs[0][2]) >= 2:
            return "false_positive"
        return "real_fail"
    return "real_fail"


def pre_oven_fail_kind_label(kind: str) -> str:
    return {"real_fail": "真不良", "false_positive": "误报", "pass": "", "unknown": ""}.get(
        kind or "", ""
    )


def pre_oven_fail_items_for_confirm(
    fail_summary: Optional[str],
    *,
    model_code: str = "",
    suffix_map: Optional[dict[str, str]] = None,
    db: Optional[Session] = None,
) -> list[dict[str, str]]:
    """后焊扫码弹窗：解析真不良位号与现象（中文）。"""
    sm = suffix_map
    if sm is None and db is not None and (model_code or "").strip():
        sm = build_pre_oven_refdes_suffix_map(db, model_code)
    items: list[dict[str, str]] = []
    for ref, typ, defect in _parse_fail_segments(fail_summary):
        typ_zh = _part_type_zh(typ)
        defect_zh = _defect_token_zh(defect)
        ref_disp = format_pre_oven_ref(ref, typ, suffix_map=sm)
        label = ref_disp
        if typ_zh:
            label += f"（{typ_zh}）"
        label += defect_zh
        items.append(
            {
                "ref": ref_disp,
                "ref_raw": ref,
                "part_type": typ,
                "part_type_zh": typ_zh,
                "defect": defect,
                "defect_zh": defect_zh,
                "label": label,
            }
        )
    return items


def _upsert_board(
    db: Session,
    *,
    barcode: str,
    result: str,
    tested_at: Optional[datetime],
    side: Optional[str],
    machine: Optional[str],
    source_file: str,
    program: Optional[str] = None,
    fail_summary: Optional[str] = None,
    cache: Optional[dict[str, PreOvenAoiBoardResult]] = None,
) -> bool:
    code = (barcode or "").strip()
    if not code:
        return False
    parsed = parse_pcba_barcode(code) or {}
    batch = find_laser_batch_for_barcode(db, code)
    row = None
    if cache is not None:
        row = cache.get(code)
    if row is None:
        row = db.query(PreOvenAoiBoardResult).filter(PreOvenAoiBoardResult.barcode == code).first()
    if not row:
        row = PreOvenAoiBoardResult(barcode=code)
        db.add(row)
    if cache is not None:
        cache[code] = row
    row.result = result
    # 较新测试时间才覆盖结果相关字段；否则仍更新挂单信息
    if tested_at and row.tested_at and tested_at < row.tested_at:
        # 旧文件：只补采购单等，不回退结果
        pass
    else:
        row.result = result
        row.tested_at = tested_at or row.tested_at
        row.side = (side or row.side or "")[:8] or None
        row.machine = (machine or row.machine or "炉前AOI")[:64]
        row.source_file = (source_file or "")[:256]
        if program:
            row.product_name = program[:128]
        if _map_result(result) == "PASS":
            row.fail_summary = None
        elif fail_summary is not None:
            row.fail_summary = (fail_summary or "")[:2000] or None
    row.model_mid = parsed.get("model_mid") or row.model_mid
    row.model_ver = parsed.get("model_ver") or row.model_ver
    row.laser_date = parsed.get("laser_date") or row.laser_date
    row.seq = parsed.get("seq") if parsed.get("seq") is not None else row.seq
    if batch:
        row.purchase_no = batch.purchase_no
        row.customer_id = batch.customer_id
        row.laser_batch_id = batch.id
        if batch.model_code:
            row.model_code = batch.model_code
    elif not row.model_code and parsed.get("model_code_guess"):
        row.model_code = parsed.get("model_code_guess")
    row.synced_at = datetime.utcnow()
    return True


def _sync_one_machine(
    db: Session,
    machine: dict[str, Any],
    *,
    force_all: bool = False,
    max_files: int = 0,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """单台炉前 AOI：扫 mes_data 根目录 CSV，写入炉前 AOI 表。"""
    mid = machine["id"]
    user = machine["username"]
    pwd = machine["password"]
    share_root = _share_root(machine)
    out: dict[str, Any] = {
        "machine_id": mid,
        "share": share_root,
        "files_seen": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "boards_upserted": 0,
        "errors": [],
    }
    from smb_session import win_net_use, win_net_use_delete

    try:
        last_mtime = (
            db.query(func.max(PreOvenAoiSyncFile.file_mtime))
            .filter(PreOvenAoiSyncFile.machine_id == mid)
            .scalar()
        )
        last_mtime_f = float(last_mtime or 0)
        floor = 0.0
        if lookback_days > 0 and not force_all:
            floor = time.time() - lookback_days * 86400
        if force_all or last_mtime_f <= 0:
            thresh = floor
        else:
            thresh = max(floor, last_mtime_f - _WATERMARK_OVERLAP_SEC)

        ok, msg = win_net_use(share_root, user, pwd)
        if not ok:
            out["errors"].append(f"无法连接 {share_root}: {msg}")
            return out

        try:
            entries = list(os.scandir(share_root))
        except Exception as e:
            out["errors"].append(f"列举失败: {e}")
            return out

        csvs = [
            e
            for e in entries
            if e.is_file() and e.name.lower().endswith(".csv")
        ]
        out["files_seen"] = len(csvs)
        # 新文件优先
        csvs.sort(key=lambda e: e.stat().st_mtime, reverse=True)
        processed = 0
        pending_by_code: dict[str, PreOvenAoiBoardResult] = {}
        for ent in csvs:
            try:
                st = ent.stat()
                mtime = float(st.st_mtime)
                size = int(st.st_size)
            except Exception:
                out["files_skipped"] += 1
                continue
            if mtime < thresh:
                out["files_skipped"] += 1
                continue
            exists = (
                db.query(PreOvenAoiSyncFile.id)
                .filter(
                    PreOvenAoiSyncFile.machine_id == mid,
                    PreOvenAoiSyncFile.filename == ent.name,
                    PreOvenAoiSyncFile.file_mtime == mtime,
                    PreOvenAoiSyncFile.file_size == size,
                )
                .first()
            )
            m = _FNAME.match(ent.name)
            fname_barcode = (m.group("barcode") if m else "") or ""
            fname_res = _map_result(m.group("res") if m else "")
            if exists and not force_all:
                # 已同步过但 FAIL 缺不良摘要时，补读 CSV（不影响扫码卡控）
                if fname_res == "FAIL" and fname_barcode:
                    row0 = pending_by_code.get(fname_barcode)
                    if row0 is None:
                        row0 = (
                            db.query(PreOvenAoiBoardResult)
                            .filter(PreOvenAoiBoardResult.barcode == fname_barcode)
                            .first()
                        )
                    if row0 and not (row0.fail_summary or "").strip():
                        pass  # fall through
                    else:
                        out["files_skipped"] += 1
                        continue
                else:
                    out["files_skipped"] += 1
                    continue

            tested_at = _ts_from_filename(m.group("ts")) if m else None

            try:
                raw = open(ent.path, "rb").read()
            except Exception as e:
                out["errors"].append(f"{ent.name}: 读取失败 {e}")
                continue
            csv_text = _read_text(raw)
            meta = _meta_from_csv(csv_text)
            barcode = (fname_barcode or meta.get("barcode") or "").strip()
            if not barcode:
                # 无条码文件无法挂单，仍记同步文件避免反复读
                db.add(
                    PreOvenAoiSyncFile(
                        machine_id=mid,
                        filename=ent.name,
                        file_mtime=mtime,
                        file_size=size,
                        row_count=0,
                    )
                )
                out["files_skipped"] += 1
                processed += 1
                if max_files and processed >= max_files:
                    break
                continue

            result = fname_res
            if result == "UNKNOWN":
                result = _map_result(meta.get("result") or "")
            if meta.get("tested_at"):
                tested_at = _parse_tested_at(meta["tested_at"]) or tested_at
            side = meta.get("side")
            machine_name = meta.get("machine") or "炉前AOI"
            program = meta.get("program")
            fail_summary = None
            if _map_result(result) == "FAIL":
                fail_summary = _fail_summary_from_csv(csv_text)

            if _upsert_board(
                db,
                barcode=barcode,
                result=result or "UNKNOWN",
                tested_at=tested_at,
                side=side,
                machine=machine_name,
                source_file=ent.name,
                program=program,
                fail_summary=fail_summary,
                cache=pending_by_code,
            ):
                out["boards_upserted"] += 1

            if not exists:
                db.add(
                    PreOvenAoiSyncFile(
                        machine_id=mid,
                        filename=ent.name,
                        file_mtime=mtime,
                        file_size=size,
                        row_count=1,
                    )
                )
            out["files_processed"] += 1
            processed += 1
            if processed % 50 == 0:
                db.commit()
                pending_by_code.clear()
            if max_files and processed >= max_files:
                break

        db.commit()
    except Exception as e:
        logger.exception("炉前AOI同步失败")
        out["errors"].append(str(e))
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            win_net_use_delete(share_root)
        except Exception:
            pass
    return out


def sync_pre_oven_aoi_from_share(
    db: Optional[Session] = None,
    *,
    force_all: bool = False,
) -> dict[str, Any]:
    """抓取配置中全部炉前 AOI 机台 CSV 并入库（多机合计统计）。"""
    own = db is None
    if own:
        db = SessionLocal()
    assert db is not None
    cfg = _pre_oven_cfg()
    machines = cfg["machines"]
    results: list[dict[str, Any]] = []
    total: dict[str, Any] = {
        "status": "ok",
        "machines": results,
        "files_seen": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "boards_upserted": 0,
        "errors": [],
        "share": ",".join(_share_root(m) for m in machines),
    }
    try:
        for m in machines:
            one = _sync_one_machine(
                db,
                m,
                force_all=force_all,
                max_files=int(cfg.get("max_files") or 0),
                lookback_days=int(cfg.get("lookback_days") or 30),
            )
            results.append(one)
            for key in ("files_seen", "files_processed", "files_skipped", "boards_upserted"):
                total[key] += int(one.get(key) or 0)
            total["errors"].extend(one.get("errors") or [])
    finally:
        if own:
            db.close()
    return total


def counts_by_purchase_model(db: Session, purchase_nos: list[str]) -> dict[tuple[str, str], int]:
    """订单列表：按 (purchase_no, model_norm) 统计炉前 AOI 板数。"""
    from engineering_service import normalize_code

    out: dict[tuple[str, str], int] = {}
    if not purchase_nos:
        return out
    rows = (
        db.query(
            PreOvenAoiBoardResult.purchase_no,
            PreOvenAoiBoardResult.model_code,
            func.count(PreOvenAoiBoardResult.id),
        )
        .filter(
            PreOvenAoiBoardResult.purchase_no.in_(purchase_nos),
            PreOvenAoiBoardResult.purchase_no.isnot(None),
            PreOvenAoiBoardResult.purchase_no != "",
        )
        .group_by(PreOvenAoiBoardResult.purchase_no, PreOvenAoiBoardResult.model_code)
        .all()
    )
    for pn, model, n in rows:
        pk = (pn or "").strip()
        mk = normalize_code(model)
        if pk and mk:
            out[(pk, mk)] = out.get((pk, mk), 0) + int(n or 0)
    return out


def boards_for_pre_oven_purchase(
    db: Session,
    purchase_no: str,
    *,
    customer_id: str = "",
    model_code: str = "",
    keyword: str = "",
    result: str = "",
    include_items: bool = True,
    limit: int = 5000,
) -> dict[str, Any]:
    """炉前 AOI 明细（只读）：合计 + PASS/FAIL + 板码列表。不写扫码闸。"""
    from engineering_service import normalize_code
    from sqlalchemy import func as sa_func

    pn = (purchase_no or "").strip()
    mc = (model_code or "").strip()
    cid = (customer_id or "").strip()
    model_norm = normalize_code(mc) if mc else ""

    def _scoped_q():
        q = db.query(PreOvenAoiBoardResult).filter(PreOvenAoiBoardResult.purchase_no == pn)
        if cid:
            q = q.filter(PreOvenAoiBoardResult.customer_id == cid)
        if mc:
            cand = q.all()
            ids = [
                r.id
                for r in cand
                if normalize_code(r.model_code) == model_norm or (r.model_code or "").strip() == mc
            ]
            if not ids:
                return db.query(PreOvenAoiBoardResult).filter(sa_func.false())
            return db.query(PreOvenAoiBoardResult).filter(PreOvenAoiBoardResult.id.in_(ids))
        return q

    result_u = sa_func.upper(PreOvenAoiBoardResult.result)
    total_n = int(_scoped_q().count() or 0)
    pass_n = int(_scoped_q().filter(result_u == "PASS").count() or 0)
    machine_fail_rows = _scoped_q().filter(result_u.in_(("FAIL", "FALL", "NG"))).all()
    real_fail_n = 0
    false_positive_n = 0
    for r in machine_fail_rows:
        kind = pre_oven_fail_kind(result=r.result, fail_summary=r.fail_summary)
        if kind == "false_positive":
            false_positive_n += 1
        else:
            real_fail_n += 1
    fail_n = real_fail_n

    items: list[dict] = []
    items_truncated = False
    result_filter = (result or "").strip().upper()
    kw = (keyword or "").strip()
    # 默认拉明细（与其它工序抽屉一致）；result=ALL 或空都返回列表
    if include_items:
        q = _scoped_q()
        if kw:
            q = q.filter(PreOvenAoiBoardResult.barcode.like(f"%{kw}%"))
        if result_filter in ("FAIL", "FALL", "NG"):
            q = q.filter(result_u.in_(("FAIL", "FALL", "NG")))
        elif result_filter == "FALSE_POSITIVE":
            q = q.filter(result_u.in_(("FAIL", "FALL", "NG")))
        elif result_filter == "PASS":
            q = q.filter(result_u == "PASS")
        elif result_filter and result_filter not in ("ALL", ""):
            q = q.filter(result_u == result_filter)
        lim = max(1, min(int(limit or 5000), 20000))
        item_total = int(q.count() or 0)
        rows = (
            q.order_by(PreOvenAoiBoardResult.tested_at.desc(), PreOvenAoiBoardResult.id.desc())
            .limit(lim)
            .all()
        )
        items_truncated = item_total > len(rows)
        filtered_rows: list[tuple[Any, str]] = []
        for r in rows:
            kind = pre_oven_fail_kind(result=r.result, fail_summary=r.fail_summary)
            if result_filter in ("FAIL", "FALL", "NG") and kind != "real_fail":
                continue
            if result_filter == "FALSE_POSITIVE" and kind != "false_positive":
                continue
            filtered_rows.append((r, kind))
        refdes_cache: dict[str, dict[str, str]] = {}

        def _suffix_map_for(row_model: Optional[str]) -> dict[str, str]:
            code = (row_model or mc or "").strip()
            if not code:
                return {}
            if code not in refdes_cache:
                refdes_cache[code] = build_pre_oven_refdes_suffix_map(db, code)
            return refdes_cache[code]

        items = [
            {
                "barcode": r.barcode,
                "model_code": r.model_code,
                "laser_date": r.laser_date,
                "seq": r.seq,
                "side": r.side,
                "result": (
                    "FAIL"
                    if (r.result or "").upper() in ("FALL", "NG")
                    else (r.result or "")
                ),
                "machine": r.machine,
                "tested_at": r.tested_at.isoformat() if r.tested_at else None,
                "source_file": r.source_file,
                "fail_summary": r.fail_summary,
                "fail_reason": format_pre_oven_fail_summary(
                    r.fail_summary,
                    model_code=r.model_code or mc,
                    suffix_map=_suffix_map_for(r.model_code),
                ),
                "fail_kind": kind,
                "fail_kind_label": pre_oven_fail_kind_label(kind),
            }
            for r, kind in filtered_rows
        ]

    return {
        "purchase_no": pn,
        "model_code": model_code or "",
        "total": total_n,
        "pass_count": pass_n,
        "fail_count": fail_n,
        "false_positive_count": false_positive_n,
        "unknown_count": max(0, total_n - pass_n - real_fail_n - false_positive_n),
        "items_limit": limit,
        "items_truncated": items_truncated,
        "result_filter": result_filter or "",
        "items": items,
    }


def backfill_pre_oven_fail_summaries(
    db: Optional[Session] = None,
    *,
    limit: int = 3000,
) -> dict[str, Any]:
    """按 source_file 回读共享盘，补 FAIL 板的不良摘要（不影响扫码卡控）。"""
    own = db is None
    if own:
        db = SessionLocal()
    assert db is not None
    cfg = _pre_oven_cfg()
    machine_by_id = {m["id"]: m for m in cfg["machines"]}
    default_machine = cfg["machines"][0] if cfg["machines"] else None
    out: dict[str, Any] = {"updated": 0, "skipped": 0, "errors": []}
    from smb_session import win_net_use, win_net_use_delete
    from sqlalchemy import or_

    rows = (
        db.query(PreOvenAoiBoardResult)
        .filter(
            PreOvenAoiBoardResult.result.in_(("FAIL", "FALL", "NG")),
            or_(
                PreOvenAoiBoardResult.fail_summary.is_(None),
                PreOvenAoiBoardResult.fail_summary == "",
            ),
            PreOvenAoiBoardResult.source_file.isnot(None),
            PreOvenAoiBoardResult.source_file != "",
        )
        .order_by(PreOvenAoiBoardResult.id.desc())
        .limit(max(1, min(int(limit or 3000), 20000)))
        .all()
    )
    if not rows:
        if own:
            db.close()
        return out

    connected: set[str] = set()

    def _ensure_share(machine: dict[str, Any]) -> Optional[str]:
        root = _share_root(machine)
        if root in connected:
            return root
        ok, msg = win_net_use(root, machine["username"], machine["password"])
        if not ok:
            out["errors"].append(f"无法连接 {root}: {msg}")
            return None
        connected.add(root)
        return root

    try:
        for row in rows:
            fname = (row.source_file or "").strip()
            if not fname:
                out["skipped"] += 1
                continue
            sync_file = (
                db.query(PreOvenAoiSyncFile)
                .filter(PreOvenAoiSyncFile.filename == fname)
                .order_by(PreOvenAoiSyncFile.processed_at.desc())
                .first()
            )
            machine = machine_by_id.get((sync_file.machine_id if sync_file else "") or "") or default_machine
            if not machine:
                out["skipped"] += 1
                continue
            share_root = _ensure_share(machine)
            if not share_root:
                out["skipped"] += 1
                continue
            path = os.path.join(share_root, fname)
            try:
                raw = open(path, "rb").read()
            except Exception as e:
                out["errors"].append(f"{fname}: {e}")
                out["skipped"] += 1
                continue
            summary = _fail_summary_from_csv(_read_text(raw))
            if not summary:
                out["skipped"] += 1
                continue
            row.fail_summary = summary[:2000]
            row.synced_at = datetime.utcnow()
            out["updated"] += 1
        db.commit()
    except Exception as e:
        out["errors"].append(str(e))
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        for root in connected:
            try:
                win_net_use_delete(root)
            except Exception:
                pass
        if own:
            db.close()
    return out
