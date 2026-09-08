"""DIP 首件对料：按订单 DIP BOM 逐项核对料号（拍照 OCR），并上传一张首件总图。

独立于产线扫码写路径，不改 process-scan / packing 语义。
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from engineering_service import normalize_code, order_kitting, suggest_bom_model
from models import (
    BomLine,
    DipFirstArticleLine,
    DipFirstArticleSession,
    SrmOrder,
)

logger = logging.getLogger(__name__)

STATIC_ROOT = Path(__file__).resolve().parent / "static"
IMAGE_ROOT = STATIC_ROOT / "dip_fai_images"

_OCR = None
_OCR_WARMING = False
_PART_LIKE = re.compile(r"[0-9A-Z]{2,}(?:-[0-9A-Z]+){1,4}", re.I)

# 料号标签 OCR：长边限制（过大几乎不提升准确率，却明显拖慢）
_OCR_MAX_SIDE = 960
_ARCHIVE_MAX_SIDE = 1280
_ARCHIVE_JPEG_QUALITY = 85


def _get_ocr():
    global _OCR
    if _OCR is not None:
        return _OCR
    try:
        from rapidocr_onnxruntime import RapidOCR

        # 标签多为正向；关 cls + 缩小检测边长，显著加快现场核对
        _OCR = RapidOCR(
            use_cls=False,
            max_side_len=_OCR_MAX_SIDE,
            det_limit_side_len=640,
            det_limit_type="max",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("RapidOCR 初始化失败: %s", exc)
        _OCR = False
    return _OCR


def warm_ocr() -> None:
    """后台预热 OCR，避免首张照片冷启动过久。"""
    global _OCR_WARMING
    if _OCR_WARMING:
        return
    _OCR_WARMING = True
    try:
        import numpy as np

        ocr = _get_ocr()
        if not ocr:
            return
        dummy = np.zeros((64, 320, 3), dtype=np.uint8)
        ocr(dummy, use_cls=False)
        logger.info("DIP 首件 OCR 已预热")
    except Exception as exc:  # noqa: BLE001
        logger.warning("DIP 首件 OCR 预热失败: %s", exc)


def _load_rgb_image(data: bytes):
    from io import BytesIO

    from PIL import Image, ImageOps

    img = Image.open(BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def _resize_max_side(img, max_side: int):
    from PIL import Image

    w, h = img.size
    m = max(w, h)
    if m <= max_side or max_side <= 0:
        return img
    scale = max_side / float(m)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return img.resize((nw, nh), Image.Resampling.BILINEAR)


def _image_to_jpeg_bytes(img, quality: int = _ARCHIVE_JPEG_QUALITY) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _prepare_for_ocr(data: bytes) -> tuple[Any, bytes]:
    """返回 (numpy RGB, 存档 JPEG bytes)。"""
    import numpy as np
    from PIL import Image  # noqa: F401 — Resampling

    img = _load_rgb_image(data)
    ocr_img = _resize_max_side(img, _OCR_MAX_SIDE)
    archive_img = _resize_max_side(img, _ARCHIVE_MAX_SIDE)
    return np.asarray(ocr_img), _image_to_jpeg_bytes(archive_img)


def _ocr_run(ocr, arr) -> str:
    result, _ = ocr(arr, use_cls=False)
    if not result:
        return ""
    parts = []
    for item in result:
        if not item or len(item) < 2:
            continue
        txt = item[1]
        if isinstance(txt, (list, tuple)) and txt:
            txt = txt[0]
        parts.append(str(txt or "").strip())
    return "\n".join(p for p in parts if p)


def _ocr_image_bytes(data: bytes) -> str:
    ocr = _get_ocr()
    if not ocr:
        return ""
    try:
        arr, _ = _prepare_for_ocr(data)
        text = _ocr_run(ocr, arr)
        # 手写反光时再试反色增强，取更像料号的结果
        if len(_digits_key(text)) < 6:
            try:
                from PIL import Image, ImageOps, ImageEnhance
                import numpy as np

                img = Image.fromarray(arr)
                inv = ImageEnhance.Contrast(ImageOps.invert(ImageOps.grayscale(img))).enhance(1.8)
                alt = _ocr_run(ocr, np.asarray(inv.convert("RGB")))
                if len(_digits_key(alt)) > len(_digits_key(text)):
                    text = alt
            except Exception:
                pass
        return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR 识别失败: %s", exc)
        return ""


def _ocr_and_archive(data: bytes) -> tuple[str, bytes]:
    """一次解码：OCR + 压缩存档图。"""
    ocr = _get_ocr()
    try:
        arr, archive = _prepare_for_ocr(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("图片解码失败: %s", exc)
        return "", data
    if not ocr:
        return "", archive
    try:
        text = _ocr_run(ocr, arr)
        if len(_digits_key(text)) < 6:
            try:
                from PIL import Image, ImageOps, ImageEnhance
                import numpy as np

                img = Image.fromarray(arr)
                inv = ImageEnhance.Contrast(ImageOps.invert(ImageOps.grayscale(img))).enhance(1.8)
                alt = _ocr_run(ocr, np.asarray(inv.convert("RGB")))
                if len(_digits_key(alt)) > len(_digits_key(text)):
                    text = alt
            except Exception:
                pass
        return text, archive
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR 识别失败: %s", exc)
        return "", archive


def _compact(code: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", normalize_code(code))


# 手写/OCR 常见形近字 → 料号数字（仅用于相对清单模糊匹配，不用于自由识别）
_OCR_DIGIT_MAP = str.maketrans(
    {
        "O": "0",
        "Q": "0",
        "D": "0",
        "U": "0",
        "V": "0",
        "C": "0",
        "I": "1",
        "L": "1",
        "|": "1",
        "Z": "2",
        "S": "5",
        "B": "8",
        "G": "6",
    }
)


def _digits_key(value: str) -> str:
    compact = _compact(value).translate(_OCR_DIGIT_MAP)
    return re.sub(r"[^0-9]", "", compact)


def _is_digit_subsequence(small: str, big: str) -> bool:
    if not small:
        return False
    it = iter(big)
    return all(ch in it for ch in small)


def _fuzzy_code_score(ocr_text: str, expected: str) -> float:
    """相对清单候选的模糊分（0~1）。OCR 残缺时仍可比对数字骨架。"""
    from difflib import SequenceMatcher

    a = _digits_key(ocr_text)
    b = _digits_key(expected)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.92
    if len(a) >= 4 and _is_digit_subsequence(a, b):
        return min(0.88, 0.55 + 0.35 * (len(a) / max(len(b), 1)))
    if len(a) >= 3 and _is_digit_subsequence(a, b):
        return min(0.72, 0.45 + 0.25 * (len(a) / max(len(b), 1)))
    return float(SequenceMatcher(None, a, b).ratio())


def _rank_fuzzy_candidates(
    lines: list[DipFirstArticleLine],
    ocr_text: str,
    *,
    customer_id: str = "",
    limit: int = 5,
) -> list[dict[str, Any]]:
    """对未通过行按 OCR 模糊分排序，供人工确认弹窗。"""
    pending = [x for x in lines if x.status != "pass"]
    scored: list[tuple[float, DipFirstArticleLine, str]] = []
    for ln in pending:
        aliases = _line_match_codes(ln.material_code or "", customer_id)
        best = 0.0
        best_alias = ln.material_code or ""
        for code in aliases or [ln.material_code or ""]:
            sc = _fuzzy_code_score(ocr_text, code or "")
            if sc > best:
                best = sc
                best_alias = code or ln.material_code or ""
        scored.append((best, ln, best_alias))
    scored.sort(key=lambda x: (-x[0], len(_compact(x[1].material_code or "")), x[1].sort_no))
    out: list[dict[str, Any]] = []
    for sc, ln, alias in scored[: max(1, limit)]:
        out.append(
            {
                "line_id": ln.id,
                "material_code": ln.material_code,
                "matched_alias": alias,
                "score": round(float(sc), 3),
            }
        )
    return out


def _try_fuzzy_unique_hit(
    lines: list[DipFirstArticleLine],
    ocr_text: str,
    *,
    customer_id: str = "",
) -> tuple[Optional[DipFirstArticleLine], str]:
    """高置信且与第二名拉开时，才自动当作命中（避免手写误杀）。"""
    ranked = _rank_fuzzy_candidates(lines, ocr_text, customer_id=customer_id, limit=3)
    if not ranked:
        return None, ""
    top = ranked[0]
    second = ranked[1]["score"] if len(ranked) > 1 else 0.0
    if top["score"] >= 0.86 and (top["score"] - second) >= 0.12:
        hit = next((x for x in lines if x.id == top["line_id"]), None)
        return hit, top.get("matched_alias") or top.get("material_code") or ""
    return None, ""


def _is_dip_line(mount_type: str, process: str) -> bool:
    mt = (mount_type or "").strip().upper()
    proc = (process or "").strip().upper()
    if mt == "DIP":
        return True
    if "DIP" in proc or "插件" in (process or ""):
        return True
    return False


def _save_image(session_id: int, kind: str, raw: bytes, content_type: str = "image/jpeg") -> str:
    IMAGE_ROOT.mkdir(parents=True, exist_ok=True)
    folder = IMAGE_ROOT / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".jpg"
    ct = (content_type or "").lower()
    if "png" in ct:
        ext = ".png"
    elif "webp" in ct:
        ext = ".webp"
    name = f"{kind}_{uuid.uuid4().hex[:10]}{ext}"
    path = folder / name
    path.write_bytes(raw)
    return f"dip_fai_images/{session_id}/{name}"


def resolve_image_path(rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if ".." in rel or not rel.startswith("dip_fai_images/"):
        raise ValueError("非法图片路径")
    path = (STATIC_ROOT / rel).resolve()
    if not str(path).startswith(str(STATIC_ROOT.resolve())):
        raise ValueError("非法图片路径")
    if not path.is_file():
        raise FileNotFoundError("图片不存在")
    return path


def _serialize_line(row: DipFirstArticleLine) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "bom_line_id": row.bom_line_id,
        "seq": row.seq,
        "material_code": row.material_code,
        "material_name": row.material_name,
        "spec": row.spec,
        "position": row.position,
        "qty_per": row.qty_per,
        "process": row.process,
        "mount_type": row.mount_type,
        "status": row.status,
        "ocr_text": row.ocr_text,
        "recognized_code": row.recognized_code,
        "verify_method": row.verify_method,
        "has_material_image": bool(row.material_image_rel),
        "verified_by": row.verified_by,
        "verified_at": row.verified_at.isoformat(sep=" ") if row.verified_at else None,
        "sort_no": row.sort_no,
    }


def _serialize_session(row: DipFirstArticleSession, lines: Optional[list[DipFirstArticleLine]] = None) -> dict[str, Any]:
    line_rows = lines if lines is not None else []
    passed = sum(1 for x in line_rows if x.status == "pass")
    pending = sum(1 for x in line_rows if x.status == "pending")
    failed = sum(1 for x in line_rows if x.status == "fail")
    return {
        "id": row.id,
        "line_key": row.line_key,
        "purchase_no": row.purchase_no,
        "model_code": row.model_code,
        "customer_name": row.customer_name,
        "bom_model_id": row.bom_model_id,
        "status": row.status,
        "operator": row.operator,
        "has_board_image": bool(row.board_image_rel),
        "board_image_rel": row.board_image_rel,
        "remark": row.remark,
        "created_at": row.created_at.isoformat(sep=" ") if row.created_at else None,
        "completed_at": row.completed_at.isoformat(sep=" ") if row.completed_at else None,
        "line_total": len(line_rows),
        "line_passed": passed,
        "line_pending": pending,
        "line_failed": failed,
        "lines": [_serialize_line(x) for x in line_rows],
    }


def _match_one_code(expected: str, ocr_text: str) -> tuple[bool, str]:
    """单料号与 OCR/扫码文本比对。返回 (是否命中, 识别到的近似料号)。"""
    exp = normalize_code(expected)
    exp_c = _compact(expected)
    text = normalize_code(ocr_text or "")
    text_c = _compact(ocr_text or "")
    if not exp:
        return False, ""
    if exp and exp in text:
        return True, exp
    if exp_c and len(exp_c) >= 6 and exp_c in text_c:
        return True, exp
    best = ""
    for m in _PART_LIKE.finditer(text.replace("\n", " ")):
        cand = normalize_code(m.group(0))
        if not cand:
            continue
        if cand == exp or _compact(cand) == exp_c:
            return True, cand
        if exp in cand or cand in exp or (_compact(cand) and _compact(cand) in exp_c):
            best = cand or best
    return False, best


def match_material_code(
    expected: str,
    ocr_text: str,
    *,
    also_codes: Optional[list[str] | set[str]] = None,
) -> tuple[bool, str]:
    """BOM 主料号 + 可选替代料号，任一命中即通过。"""
    codes: list[str] = []
    seen: set[str] = set()
    for raw in (expected, *(also_codes or [])):
        n = normalize_code(raw or "")
        if not n or n in seen:
            continue
        seen.add(n)
        codes.append(n)
    if not codes:
        return False, ""
    # 长料号优先，减少短码误伤
    codes.sort(key=lambda c: len(_compact(c)), reverse=True)
    best = ""
    for code in codes:
        ok, recog = _match_one_code(code, ocr_text)
        if recog and len(recog) > len(best):
            best = recog
        if ok:
            return True, recog or code
    return False, best


def _session_customer_id(db: Session, sess: DipFirstArticleSession) -> str:
    """替代料按客户隔离：优先订单 customer_id，再 BOM。"""
    key = (sess.line_key or "").strip()
    if key:
        order = db.query(SrmOrder).filter(SrmOrder.line_key == key).first()
        if order and (order.customer_id or "").strip():
            return (order.customer_id or "").strip()
    bom_id = sess.bom_model_id
    if bom_id:
        from models import BomModel

        bom = db.query(BomModel).filter(BomModel.id == int(bom_id)).first()
        if bom and (bom.customer_id or "").strip():
            return (bom.customer_id or "").strip()
    return ""


def _line_match_codes(material_code: str, customer_id: str) -> list[str]:
    """首件核对可用的料号集合：BOM 行 + 客户替代组。"""
    from substitution_service import get_substitute_group

    primary = normalize_code(material_code or "")
    if not primary:
        return []
    group = get_substitute_group(primary, customer_id) or {primary}
    out = [primary]
    for g in group:
        n = normalize_code(g)
        if n and n not in out:
            out.append(n)
    return out


def _collect_dip_items(db: Session, bom_id: int) -> list[dict[str, Any]]:
    """与订单工作台 BOM 一致：按贴装分类取全部 DIP 行；再回落 process 含 DIP/插件。"""
    from models import BomModel
    from material_mount_service import load_mount_overrides
    from mount_classification import classify_lines_mount, load_placement_index

    bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
    if not bom:
        return []
    bom_lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom_id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    if not bom_lines:
        return []

    dip_items: list[dict[str, Any]] = []
    seen: set[int] = set()
    try:
        placement_index = load_placement_index(db, bom)
        _profile, mounts = classify_lines_mount(
            bom_lines,
            placement_index=placement_index,
            profile_override=bom.mount_profile_override,
            master_overrides=load_mount_overrides(db, internal_code=bom.internal_code or ""),
            internal_code=bom.internal_code or "",
        )
        for bl, mount in zip(bom_lines, mounts):
            mt = str((mount or {}).get("mount_type") or "").strip().upper()
            if mt == "DIP" or _is_dip_line(mt, bl.process or ""):
                seen.add(bl.id)
                dip_items.append(
                    {
                        "material_code": bl.material_code,
                        "material_name": bl.material_name,
                        "spec": bl.spec,
                        "position": bl.position,
                        "qty_per": bl.qty_per,
                        "process": bl.process,
                        "mount_type": "DIP",
                        "bom_line_id": bl.id,
                        "seq": bl.seq,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("DIP 首件贴装分类失败，回落 process: %s", exc)

    if not dip_items:
        for bl in bom_lines:
            if bl.id in seen:
                continue
            if _is_dip_line("", bl.process or ""):
                dip_items.append(
                    {
                        "material_code": bl.material_code,
                        "material_name": bl.material_name,
                        "spec": bl.spec,
                        "position": bl.position,
                        "qty_per": bl.qty_per,
                        "process": bl.process,
                        "mount_type": "DIP",
                        "bom_line_id": bl.id,
                        "seq": bl.seq,
                    }
                )
    return dip_items


def start_session(db: Session, line_key: str, operator: str) -> dict[str, Any]:
    key = (line_key or "").strip()
    if not key:
        raise ValueError("请选择订单")
    order = db.query(SrmOrder).filter(SrmOrder.line_key == key).first()
    if not order:
        raise ValueError("订单不存在")

    bom_id = order.bom_model_id
    if not bom_id:
        bom = suggest_bom_model(db, order)
        if bom:
            order.bom_model_id = bom.id
            bom_id = bom.id
            db.flush()
    if not bom_id:
        raise ValueError("订单未绑定 BOM，请先在工程资料绑定")

    dip_items = _collect_dip_items(db, int(bom_id))
    if not dip_items:
        # 齐套口径兜底
        kit = order_kitting(db, key)
        dip_items = [
            x
            for x in (kit.get("lines") or [])
            if _is_dip_line(str(x.get("mount_type") or ""), str(x.get("process") or ""))
        ]
    if not dip_items:
        raise ValueError("该订单 BOM 无 DIP/插件物料，无法做 DIP 首件")

    # 同一订单进行中的会话：直接续做（料号不全时提示取消重开）
    existing = (
        db.query(DipFirstArticleSession)
        .filter(
            DipFirstArticleSession.line_key == key,
            DipFirstArticleSession.status == "in_progress",
        )
        .order_by(DipFirstArticleSession.id.desc())
        .first()
    )
    if existing:
        lines = (
            db.query(DipFirstArticleLine)
            .filter(DipFirstArticleLine.session_id == existing.id)
            .order_by(DipFirstArticleLine.sort_no.asc(), DipFirstArticleLine.id.asc())
            .all()
        )
        return _serialize_session(existing, lines)

    now = datetime.utcnow()
    sess = DipFirstArticleSession(
        line_key=key,
        purchase_no=(order.purchase_no or "").strip(),
        model_code=(order.product_goods_no or "").strip(),
        customer_name=(order.customer_name or "").strip(),
        bom_model_id=bom_id,
        status="in_progress",
        operator=(operator or "").strip(),
        created_at=now,
    )
    db.add(sess)
    db.flush()

    for i, item in enumerate(dip_items):
        code = str(item.get("material_code") or "").strip()
        db.add(
            DipFirstArticleLine(
                session_id=sess.id,
                bom_line_id=item.get("bom_line_id"),
                seq=str(item.get("seq") or "") or None,
                material_code=code,
                material_name=item.get("material_name"),
                spec=item.get("spec"),
                position=item.get("position"),
                qty_per=float(item.get("qty_per") or 1),
                process=item.get("process"),
                mount_type=str(item.get("mount_type") or "DIP"),
                status="pending",
                sort_no=i,
            )
        )
    db.commit()
    lines = (
        db.query(DipFirstArticleLine)
        .filter(DipFirstArticleLine.session_id == sess.id)
        .order_by(DipFirstArticleLine.sort_no.asc(), DipFirstArticleLine.id.asc())
        .all()
    )
    return _serialize_session(sess, lines)


def get_session(db: Session, session_id: int) -> dict[str, Any]:
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    lines = (
        db.query(DipFirstArticleLine)
        .filter(DipFirstArticleLine.session_id == sess.id)
        .order_by(DipFirstArticleLine.sort_no.asc(), DipFirstArticleLine.id.asc())
        .all()
    )
    return _serialize_session(sess, lines)


def verify_line_photo(
    db: Session,
    session_id: int,
    line_id: int,
    image_bytes: bytes,
    content_type: str,
    operator: str,
) -> dict[str, Any]:
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    if sess.status != "in_progress":
        raise ValueError("该首件已结束，不能再核对")
    line = (
        db.query(DipFirstArticleLine)
        .filter(DipFirstArticleLine.id == line_id, DipFirstArticleLine.session_id == session_id)
        .first()
    )
    if not line:
        raise ValueError("物料行不存在")
    if not image_bytes:
        raise ValueError("请拍照上传料号图片")

    ocr_text, archive = _ocr_and_archive(image_bytes)
    rel = _save_image(session_id, f"mat_{line_id}", archive, "image/jpeg")
    aliases = _line_match_codes(line.material_code or "", _session_customer_id(db, sess))
    ok, recognized = match_material_code(line.material_code, ocr_text, also_codes=aliases)
    line.material_image_rel = rel
    line.ocr_text = (ocr_text or "")[:4000] or None
    line.recognized_code = recognized or None
    line.verified_by = (operator or "").strip() or None
    line.verified_at = datetime.utcnow()
    if ok:
        line.status = "pass"
        line.verify_method = "ocr"
        message = "正确"
    else:
        line.status = "fail"
        line.verify_method = "ocr"
        message = "错误"
    db.commit()
    return {
        "ok": ok,
        "message": message,
        "expected_code": line.material_code,
        "recognized_code": recognized or "",
        "ocr_text": ocr_text or "",
        "line": _serialize_line(line),
        "session": get_session(db, session_id),
    }


def _match_lines_by_text(
    lines: list[DipFirstArticleLine],
    text: str,
    *,
    customer_id: str = "",
) -> tuple[Optional[DipFirstArticleLine], Optional[DipFirstArticleLine], str, str]:
    """返回 (未通过命中, 已通过命中, 命中识别码, 最佳近似码)。含客户替代料号。"""
    pending = [x for x in lines if x.status != "pass"]
    passed = [x for x in lines if x.status == "pass"]
    best_recog = ""

    def _try(candidates: list[DipFirstArticleLine]) -> tuple[Optional[DipFirstArticleLine], str]:
        nonlocal best_recog
        hit: Optional[DipFirstArticleLine] = None
        hit_recog = ""
        ordered = sorted(candidates, key=lambda x: len(_compact(x.material_code or "")), reverse=True)
        for ln in ordered:
            aliases = _line_match_codes(ln.material_code or "", customer_id)
            ok, recognized = match_material_code(ln.material_code, text, also_codes=aliases)
            if recognized and len(recognized) > len(best_recog):
                best_recog = recognized
            if ok:
                hit = ln
                hit_recog = recognized or ln.material_code
                break
        return hit, hit_recog

    hit, recog = _try(pending)
    if hit:
        return hit, None, recog, best_recog
    # 印刷体硬匹配失败：对手写残缺 OCR 做高置信模糊命中
    fuzzy_hit, fuzzy_recog = _try_fuzzy_unique_hit(pending, text, customer_id=customer_id)
    if fuzzy_hit:
        return fuzzy_hit, None, fuzzy_recog or fuzzy_hit.material_code, best_recog or fuzzy_recog
    hit_done, recog_done = _try(passed)
    if hit_done:
        return None, hit_done, recog_done, best_recog
    fuzzy_done, fuzzy_done_recog = _try_fuzzy_unique_hit(passed, text, customer_id=customer_id)
    return None, fuzzy_done, fuzzy_done_recog or recog_done, best_recog or fuzzy_done_recog


def _fail_needs_confirm_payload(
    db: Session,
    *,
    session_id: int,
    lines: list[DipFirstArticleLine],
    ocr_text: str,
    best_recog: str,
    customer_id: str,
    scanned: str = "",
) -> dict[str, Any]:
    ranked = _rank_fuzzy_candidates(lines, ocr_text or scanned, customer_id=customer_id, limit=6)
    suggest = ranked[0] if ranked else None
    empty_line = {
        "id": int(suggest["line_id"]) if suggest else 0,
        "session_id": session_id,
        "material_code": (suggest or {}).get("material_code") or "",
        "status": "pending",
        "qty_per": 0,
        "mount_type": "DIP",
        "sort_no": 0,
    }
    recog = (best_recog or scanned or "").strip()
    return {
        "ok": False,
        "needs_confirm": True,
        "message": "需要人工确认",
        "expected_code": (suggest or {}).get("material_code") or "",
        "recognized_code": recog,
        "ocr_text": (ocr_text or scanned or "")[:4000],
        "suggest_line_id": int(suggest["line_id"]) if suggest else None,
        "suggest_code": (suggest or {}).get("material_code") or "",
        "candidates": ranked,
        "line": empty_line,
        "session": get_session(db, session_id),
    }


def verify_session_photo(
    db: Session,
    session_id: int,
    image_bytes: bytes,
    content_type: str,
    operator: str,
) -> dict[str, Any]:
    """拍照后对会话内全部 DIP 料号自动匹配（不强制顺序）。

    命中未通过行 → 记为通过；命中已通过行 → 提示已核对；未命中 → 播报错误但不改状态（可重拍）。
    """
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    if sess.status != "in_progress":
        raise ValueError("该首件已结束，不能再核对")
    if not image_bytes:
        raise ValueError("请拍照上传料号图片")

    lines = (
        db.query(DipFirstArticleLine)
        .filter(DipFirstArticleLine.session_id == session_id)
        .order_by(DipFirstArticleLine.sort_no.asc(), DipFirstArticleLine.id.asc())
        .all()
    )
    if not lines:
        raise ValueError("无物料明细")

    ocr_text, archive = _ocr_and_archive(image_bytes)
    op = (operator or "").strip() or None
    customer_id = _session_customer_id(db, sess)
    hit, hit_done, recog, best_recog = _match_lines_by_text(
        lines, ocr_text, customer_id=customer_id
    )

    if hit:
        rel = _save_image(session_id, f"mat_{hit.id}", archive, "image/jpeg")
        hit.material_image_rel = rel
        hit.ocr_text = (ocr_text or "")[:4000] or None
        hit.recognized_code = recog or None
        hit.verified_by = op
        hit.verified_at = datetime.utcnow()
        hit.status = "pass"
        hit.verify_method = "ocr"
        db.commit()
        return {
            "ok": True,
            "message": "正确",
            "expected_code": hit.material_code,
            "recognized_code": recog or "",
            "ocr_text": ocr_text or "",
            "line": _serialize_line(hit),
            "session": get_session(db, session_id),
        }

    if hit_done:
        return {
            "ok": True,
            "message": "已核对",
            "expected_code": hit_done.material_code,
            "recognized_code": recog or hit_done.material_code,
            "ocr_text": ocr_text or "",
            "line": _serialize_line(hit_done),
            "session": get_session(db, session_id),
        }

    # 手写/反光导致无法可靠识别：不改状态，返回候选供 PDA 目视确认
    return _fail_needs_confirm_payload(
        db,
        session_id=session_id,
        lines=lines,
        ocr_text=ocr_text or "",
        best_recog=best_recog or "",
        customer_id=customer_id,
    )


def verify_session_scan(
    db: Session,
    session_id: int,
    scanned_code: str,
    operator: str,
) -> dict[str, Any]:
    """扫码/输入后对会话内全部 DIP 料号自动匹配（与拍照同一逻辑，不碰产线扫码）。"""
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    if sess.status != "in_progress":
        raise ValueError("该首件已结束，不能再核对")
    scanned = (scanned_code or "").strip()
    if not scanned:
        raise ValueError("请扫描或输入料号")

    lines = (
        db.query(DipFirstArticleLine)
        .filter(DipFirstArticleLine.session_id == session_id)
        .order_by(DipFirstArticleLine.sort_no.asc(), DipFirstArticleLine.id.asc())
        .all()
    )
    if not lines:
        raise ValueError("无物料明细")

    op = (operator or "").strip() or None
    customer_id = _session_customer_id(db, sess)
    hit, hit_done, recog, best_recog = _match_lines_by_text(
        lines, scanned, customer_id=customer_id
    )

    if hit:
        hit.status = "pass"
        hit.verify_method = "scan"
        hit.recognized_code = recog or hit.material_code
        hit.ocr_text = (f"[扫码] {scanned}")[:4000]
        hit.verified_by = op
        hit.verified_at = datetime.utcnow()
        db.commit()
        return {
            "ok": True,
            "message": "正确",
            "expected_code": hit.material_code,
            "recognized_code": recog or "",
            "ocr_text": scanned,
            "line": _serialize_line(hit),
            "session": get_session(db, session_id),
        }

    if hit_done:
        return {
            "ok": True,
            "message": "已核对",
            "expected_code": hit_done.material_code,
            "recognized_code": recog or hit_done.material_code,
            "ocr_text": scanned,
            "line": _serialize_line(hit_done),
            "session": get_session(db, session_id),
        }

    return _fail_needs_confirm_payload(
        db,
        session_id=session_id,
        lines=lines,
        ocr_text="",
        best_recog=best_recog or "",
        customer_id=customer_id,
        scanned=scanned,
    )


def manual_pass_line(
    db: Session,
    session_id: int,
    line_id: int,
    operator: str,
    reason: str = "",
) -> dict[str, Any]:
    """OCR 无法识别时人工确认正确（需写原因）。"""
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    if sess.status != "in_progress":
        raise ValueError("该首件已结束，不能再核对")
    line = (
        db.query(DipFirstArticleLine)
        .filter(DipFirstArticleLine.id == line_id, DipFirstArticleLine.session_id == session_id)
        .first()
    )
    if not line:
        raise ValueError("物料行不存在")
    reason = (reason or "").strip()
    if len(reason) < 2:
        raise ValueError("人工确认请填写原因（至少2字）")
    line.status = "pass"
    line.verify_method = "manual"
    line.recognized_code = line.material_code
    line.ocr_text = ((line.ocr_text or "") + f"\n[人工确认] {reason}").strip()
    line.verified_by = (operator or "").strip() or None
    line.verified_at = datetime.utcnow()
    db.commit()
    return {
        "ok": True,
        "message": "正确",
        "line": _serialize_line(line),
        "session": get_session(db, session_id),
    }


def upload_board_photo(
    db: Session,
    session_id: int,
    image_bytes: bytes,
    content_type: str,
) -> dict[str, Any]:
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    if sess.status != "in_progress":
        raise ValueError("该首件已结束，不能再上传")
    if not image_bytes:
        raise ValueError("请上传首件总图")
    try:
        img = _load_rgb_image(image_bytes)
        archive = _image_to_jpeg_bytes(_resize_max_side(img, 1600), quality=82)
        rel = _save_image(session_id, "board", archive, "image/jpeg")
        content_type = "image/jpeg"
    except Exception:  # noqa: BLE001
        rel = _save_image(session_id, "board", image_bytes, content_type)
    sess.board_image_rel = rel
    sess.board_image_content_type = (content_type or "image/jpeg")[:64]
    db.commit()
    return get_session(db, session_id)


def complete_session(db: Session, session_id: int, operator: str = "") -> dict[str, Any]:
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    if sess.status != "in_progress":
        raise ValueError("该首件已结束")
    lines = (
        db.query(DipFirstArticleLine)
        .filter(DipFirstArticleLine.session_id == sess.id)
        .order_by(DipFirstArticleLine.sort_no.asc(), DipFirstArticleLine.id.asc())
        .all()
    )
    if not lines:
        raise ValueError("无物料明细")
    pending = [x for x in lines if x.status != "pass"]
    if pending:
        raise ValueError(f"还有 {len(pending)} 项物料未确认通过")
    if not sess.board_image_rel:
        raise ValueError("请先上传一张首件总图")
    sess.status = "passed"
    sess.completed_at = datetime.utcnow()
    if operator and not sess.operator:
        sess.operator = operator.strip()
    db.commit()
    return _serialize_session(sess, lines)


def cancel_session(db: Session, session_id: int, remark: str = "") -> dict[str, Any]:
    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    if sess.status != "in_progress":
        raise ValueError("该首件已结束")
    sess.status = "cancelled"
    sess.completed_at = datetime.utcnow()
    if remark:
        sess.remark = (remark or "").strip()[:512]
    db.commit()
    return get_session(db, session_id)


def delete_session(db: Session, session_id: int) -> dict[str, Any]:
    """品质侧彻底删除首件记录及关联图片（不影响产线扫码）。"""
    import shutil

    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess:
        raise ValueError("首件记录不存在")
    sid = sess.id
    db.query(DipFirstArticleLine).filter(DipFirstArticleLine.session_id == sid).delete(
        synchronize_session=False
    )
    db.delete(sess)
    db.commit()
    folder = IMAGE_ROOT / str(sid)
    try:
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:  # noqa: BLE001
        logger.warning("删除首件图片目录失败 session=%s", sid)
    return {"ok": True, "deleted_id": sid}


def list_sessions(
    db: Session,
    *,
    keyword: str = "",
    status: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    q = db.query(DipFirstArticleSession)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (DipFirstArticleSession.purchase_no.ilike(like))
            | (DipFirstArticleSession.model_code.ilike(like))
            | (DipFirstArticleSession.customer_name.ilike(like))
            | (DipFirstArticleSession.operator.ilike(like))
        )
    st = (status or "").strip()
    if st:
        q = q.filter(DipFirstArticleSession.status == st)
    total = q.count()
    rows = (
        q.order_by(DipFirstArticleSession.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
        .all()
    )
    items = []
    for row in rows:
        n_lines = (
            db.query(DipFirstArticleLine)
            .filter(DipFirstArticleLine.session_id == row.id)
            .count()
        )
        n_pass = (
            db.query(DipFirstArticleLine)
            .filter(
                DipFirstArticleLine.session_id == row.id,
                DipFirstArticleLine.status == "pass",
            )
            .count()
        )
        items.append(
            {
                "id": row.id,
                "line_key": row.line_key,
                "purchase_no": row.purchase_no,
                "model_code": row.model_code,
                "customer_name": row.customer_name,
                "status": row.status,
                "operator": row.operator,
                "has_board_image": bool(row.board_image_rel),
                "line_total": n_lines,
                "line_passed": n_pass,
                "created_at": row.created_at.isoformat(sep=" ") if row.created_at else None,
                "completed_at": row.completed_at.isoformat(sep=" ") if row.completed_at else None,
            }
        )
    return {"total": total, "items": items, "limit": limit, "offset": offset}
