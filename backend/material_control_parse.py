"""物料管制单 PDF/图片识别：抽文本 + OCR + 正则预填字段（不落库、不改 BOM）。"""
from __future__ import annotations

import io
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CONTROL_NO = re.compile(r"\bGZ\d{6,}\b", re.I)
# 允许版本尾缀，如 112-100319-00A
_PART_CODE = re.compile(r"\b(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)\b")
# OCR 常把 120-200235-09 识别成 120200235-09
_PART_CODE_GLUED = re.compile(r"\b(\d{3})(\d{6})-(\d{2}[A-Za-z]?)\b")
# OCR 截断：120-300056-0 → 120-300056-00（末段仅 1 位且后非料号字符）
_PART_CODE_TRUNC = re.compile(r"\b(\d{3}-\d{5,6}-)(\d)(?![0-9A-Za-z])")
_ECN = re.compile(r"\bECN\d{6,}\b", re.I)
# 完整工单 * 数量（数量限 1～8 位，避免 OCR 粘连吞掉下一工单号）
# 数量后若紧跟另一料号（去空白粘连成 *6800112-100306），则回退数量边界
_WO_FULL = re.compile(
    r"(\d{4}-\d{11,14})\s*[×xX*＊]\s*(\d{1,8}(?:\.\d+)?)"
    r"(?=(?:\d{3}-\d{5,6}-\d{2}[A-Za-z]?)|(?:[^\d.]|$))",
)
_WO_BARE = re.compile(r"(\d{4}-\d{11,14})")
# 字母前缀工单（OCR 常见 S103-…；normalize 后多已转为 5103-）
_WO_ALPHA_FULL = re.compile(
    r"([A-Za-z]\d{3}-\d{8,14})\s*[×xX*＊]\s*(\d{1,8}(?:\.\d+)?)"
)
_WO_ALPHA_BARE = re.compile(r"\b([A-Za-z]\d{3}-\d{8,14})\b")
# 短尾行号 * 数量（如 004*10000），必须有乘号，避免「500\n110-料号」误匹配
_WO_SHORT = re.compile(r"(?<![\d-])(\d{3})\s*[×xX*＊]\s*(\d+(?:\.\d+)?)")
# 料号 * 用量（加料可能带 A/B 尾缀）
_MAT_QTY = re.compile(r"(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)\s*[×xX*＊]\s*(\d+(?:\.\d+)?)")
_REFDES = re.compile(r"\b([URJCQD]\d{1,3}(?:\s*[,，、/]\s*[URJCQD]\d{1,3})*)\b", re.I)
_MODEL_NEAR = re.compile(
    r"(?:管制料号|管制机型|机型)[：:\s]*([0-9-]{10,16})",
    re.I,
)
# 产品型号：IVEM12048-II（无 120- 料号时兜底）
_MODEL_NAME = re.compile(
    r"(?:管制机型|机型)[：:\s]*([A-Za-z][A-Za-z0-9._/-]{2,32})",
    re.I,
)
# 「管制120-300056-00」叙述式 PCBA
_CONTROLLED_PART = re.compile(
    r"(?:管制|管制PCBA|管制\s*PCBA)\s*[:：]?\s*(\d{3}-\d{5,6}-\d{1,2}[A-Za-z]?)",
    re.I,
)
_REASON_NEAR = re.compile(
    r"(?:管制原因|主旨说明)[：:\s/]*([^\n]{4,120})",
)
_PCBA_SECTION = re.compile(r"管制\s*PCBA\s*[:：]?\s*(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)", re.I)
_CHANGE_SENTENCE = re.compile(
    r"(\d{3}-\d{5,6}-\d{2}[A-Za-z]?).{0,24}(?:改为|更换|变成|替换为|修改为).{0,24}"
    r"(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)",
)
# 叙述：删除… / 增加…
_NARR_ACT = re.compile(
    r"(删除|刪除|增加|新增)\s*(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)"
    r"(?:[^删刪增\n]{0,160}?位号\s*[：:]\s*([URJCQD\d][^数量\n]{0,40}))?"
    r"(?:[^删刪增\n]{0,40}?数量\s*[：:]\s*(\d+(?:\.\d+)?))?",
    re.I,
)
# 表格：机型后跟工单
_MODEL_THEN_WO = re.compile(
    r"(120-\d{6}-\d{2}|030-\d{6}-\d{2})"
    r".{0,60}?"
    r"(\d{4}-\d{8,})(?:\s*[×xX*＊]\s*(\d+(?:\.\d+)?))?",
    re.S,
)
# 表格「PCBA管制」行后的管制数量
_TABLE_QTY = re.compile(r"PCBA管制\s+(\d{2,8})(?=\s*(?:\d{3}-|$))", re.I)
# 表格行：PCBA管制 + 本批数量 + 删料*用量 + 位号 + 加料*用量（位号允许 OCR 噪点如 U28,.U29）
_TABLE_BATCH_ROW = re.compile(
    r"PCBA管制\s+(\d{2,8})\s+"
    r"(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)\s*[×xX*＊]\s*(\d+(?:\.\d+)?)\s*(?:PCS|pcs|pcS)?\s*"
    r"([URJCQD][\dURJCQD,，、/.．\s]{0,48})?\s*"
    r"(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)\s*[×xX*＊]\s*(\d+(?:\.\d+)?)",
    re.I,
)

_OCR = None


def _get_ocr():
    global _OCR
    if _OCR is not None:
        return _OCR
    try:
        from rapidocr_onnxruntime import RapidOCR

        _OCR = RapidOCR()
    except Exception as exc:  # noqa: BLE001
        logger.warning("RapidOCR 初始化失败: %s", exc)
        _OCR = False
    return _OCR


def _fix_part_code(code: str) -> str:
    c = (code or "").strip()
    m = _PART_CODE_GLUED.fullmatch(c) or _PART_CODE_GLUED.search(c)
    if m and "-" not in c[:4]:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # 末段仅 1 位：补零成标准两位
    mt = re.fullmatch(r"(\d{3}-\d{5,6}-)(\d)([A-Za-z]?)", c)
    if mt:
        return f"{mt.group(1)}0{mt.group(2)}{mt.group(3)}"
    m2 = _PART_CODE.search(c)
    return m2.group(1) if m2 else c


def _normalize_wo(wo: str) -> str:
    """工单号规范化：OCR 常把 5103 认成 S103。"""
    w = (wo or "").strip()
    m = re.fullmatch(r"([SsOo])(\d{3}-\d{8,14})", w)
    if m:
        lead = "5" if m.group(1) in "Ss" else "0"
        return lead + m.group(2)
    return w


def _is_wo_no(pn: str) -> bool:
    p = _normalize_wo(pn)
    return bool(
        re.match(r"^\d{4}-\d{8,}$", p)
        or re.match(r"^[A-Za-z]\d{3}-\d{8,}$", p)
        or re.match(r"^\d{3}-\d+", p)
    )


def _extract_table_batch_changes(raw: str) -> list[dict]:
    """
    按表格行解析分批管制：
    PCBA管制 / 管制数量500 / 删料 / 位号 / 加料
    每行 = 从工单总量中抽出的一批，不是整单都换这组料。
    """
    out: list[dict] = []
    for m in _TABLE_BATCH_ROW.finditer(raw or ""):
        batch_qty = _sanitize_qty(float(m.group(1)))
        remove_code = _fix_part_code(m.group(2))
        remove_qty = float(m.group(3))
        ref_raw = (m.group(4) or "").replace(".", ",").replace("．", ",")
        ref = _merge_refdes(ref_raw)
        add_code = _fix_part_code(m.group(5))
        add_qty = float(m.group(6))
        if remove_code == add_code:
            continue
        out.append(
            {
                "control_qty": batch_qty,
                "remove_code": remove_code,
                "remove_qty": remove_qty,
                "remove_refdes": ref or None,
                "add_code": add_code,
                "add_qty": add_qty or remove_qty,
                "add_refdes": ref or None,
                "remark": None,
            }
        )
    return out


def _guess_table_qty(raw: str) -> float:
    """从表格 PCBA管制 行推断管制数量（工单号缺失时常见只剩数量）。"""
    hits = _TABLE_QTY.findall(raw or "")
    if not hits:
        hits = re.findall(
            r"(?:整机工单号\*数量|工单号\*数量)[：:\s]*[A-Za-z]?\d{3,4}-\d{8,}\s*[×xX*＊]?\s*(\d{2,8})",
            raw or "",
            re.I,
        )
    if not hits:
        return 0.0
    # 取出现最多的数量
    best, _cnt = max(((q, hits.count(q)) for q in set(hits)), key=lambda x: x[1])
    return _sanitize_qty(float(best))


def _resolve_model_code(raw: str) -> str:
    """机型优先取 120-/030- PCBA 料号，其次数字管制料号，最后产品型号。"""
    for m in _CONTROLLED_PART.finditer(raw or ""):
        fc = _fix_part_code(m.group(1))
        if fc.startswith(("120-", "030-", "118-")) and not fc.startswith("110-"):
            return fc
    mm = _MODEL_NEAR.search(raw or "")
    if mm:
        return _fix_part_code(mm.group(1))
    codes = [_fix_part_code(c) for c in _PART_CODE.findall(raw or "")]
    for c in codes:
        if c.startswith("120-") or c.startswith("030-"):
            return c
    for c in codes:
        if not c.startswith("110-"):
            return c
    mn = _MODEL_NAME.search(raw or "")
    if mn:
        name = mn.group(1).strip().rstrip("，,。.;；")
        if not re.match(r"^(PCBA|ECN|GZ)", name, re.I):
            return name
    return ""


def _refdes_near_codes(raw: str, code_a: str, code_b: str) -> str:
    """取两料号之间（及紧后）的位号，避免全文位号串组。"""
    if not raw or not code_a:
        return ""
    i1 = raw.find(code_a)
    if i1 < 0:
        return ""
    i2 = raw.find(code_b, i1 + len(code_a)) if code_b else -1
    end = (i2 + len(code_b) + 100) if i2 > i1 else (i1 + len(code_a) + 120)
    return _merge_refdes(raw[i1:end])


def _extract_narrative_changes(raw: str) -> list[dict]:
    """叙述式「删除…增加…」成对抽取。"""
    acts: list[dict] = []
    for m in _NARR_ACT.finditer(raw or ""):
        op = "remove" if str(m.group(1)).startswith(("删", "刪")) else "add"
        ref = ""
        if m.group(3):
            ref = _merge_refdes(m.group(3))
        qty = float(m.group(4)) if m.group(4) else 0.0
        acts.append(
            {
                "op": op,
                "code": _fix_part_code(m.group(2)),
                "refdes": ref or None,
                "qty": qty,
            }
        )
    out: list[dict] = []
    i = 0
    while i + 1 < len(acts):
        a, b = acts[i], acts[i + 1]
        if a["op"] == "remove" and b["op"] == "add" and a["code"] != b["code"]:
            rq = a["qty"] or b["qty"] or 1.0
            aq = b["qty"] or a["qty"] or rq
            out.append(
                {
                    "remove_code": a["code"],
                    "remove_qty": rq,
                    "remove_refdes": a["refdes"] or b["refdes"],
                    "add_code": b["code"],
                    "add_qty": aq,
                    "add_refdes": b["refdes"] or a["refdes"],
                    "remark": None,
                }
            )
            i += 2
        else:
            i += 1
    return out


def _normalize_text(text: str) -> str:
    t = (text or "").replace("\u3000", " ")
    t = t.replace("×", "*").replace("＊", "*").replace("ｘ", "*").replace("X", "*")
    t = _PART_CODE_GLUED.sub(r"\1-\2-\3", t)
    # 截断料号补零：120-300056-0 → 120-300056-00
    t = _PART_CODE_TRUNC.sub(r"\g<1>0\2", t)
    # OCR：整机工单 S103-… → 5103-…（5 常被认成 S）
    t = re.sub(r"(?<![A-Za-z0-9])[Ss](\d{3}-\d{8,14})", r"5\1", t)
    t = re.sub(r"(?<![A-Za-z0-9])[Oo](\d{3}-\d{8,14})", r"0\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t


def _merge_refdes(text: str) -> str:
    """合并全文位号；删除/新增列常重复同一串，按出现顺序去重。"""
    parts: list[str] = []
    seen: set[str] = set()
    for m in _REFDES.findall(text or ""):
        s = m.replace("，", ",").replace("、", ",").replace("/", ",")
        for p in re.split(r"\s*,\s*", s):
            tok = p.strip().upper()
            if not tok or tok in seen:
                continue
            seen.add(tok)
            parts.append(tok)
    return ",".join(parts)


def _extract_pdf_text(data: bytes) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    chunks: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            chunks.append(page.get_text("text") or "")
    return "\n".join(chunks).strip()


def _render_pdf_images(data: bytes, max_pages: int = 2, dpi: int = 200) -> list[Any]:
    import fitz
    from PIL import Image

    images = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
    return images


def _load_image(data: bytes) -> Any:
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB")


def _ocr_image(img: Any) -> str:
    ocr = _get_ocr()
    if not ocr:
        return ""
    import numpy as np

    arr = np.array(img)
    result, _ = ocr(arr)
    if not result:
        return ""
    lines = []
    for item in result:
        # item: [box, text, score]
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]))
    return "\n".join(lines)


def extract_text_from_file(filename: str, data: bytes) -> tuple[str, str]:
    """返回 (text, source) source: pdf_text|ocr|mixed"""
    name = (filename or "").lower()
    is_pdf = name.endswith(".pdf") or data[:5] == b"%PDF-"
    is_image = name.endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"))
    if not is_pdf and not is_image:
        # 尝试按魔数判断
        if data[:5] == b"%PDF-":
            is_pdf = True
        else:
            is_image = True

    warnings_src = []
    if is_pdf:
        text = _extract_pdf_text(data)
        if len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)) >= 40 and _CONTROL_NO.search(text):
            return _normalize_text(text), "pdf_text"
        ocr_parts = []
        try:
            for img in _render_pdf_images(data):
                ocr_parts.append(_ocr_image(img))
        except Exception as exc:  # noqa: BLE001
            logger.exception("PDF 渲染/OCR 失败: %s", exc)
            warnings_src.append(str(exc))
        ocr_text = "\n".join(ocr_parts)
        merged = _normalize_text((text + "\n" + ocr_text).strip())
        return merged, "mixed" if text.strip() else "ocr"

    img = _load_image(data)
    return _normalize_text(_ocr_image(img)), "ocr"


def _expand_short_wos(orders: list[dict], full_prefix: Optional[str]) -> list[dict]:
    if not full_prefix:
        return orders
    out = []
    for o in orders:
        pn = o["purchase_no"]
        if re.fullmatch(r"\d{3}", pn):
            o = {**o, "purchase_no": full_prefix + pn}
        out.append(o)
    return out


def _dedupe_orders(orders: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for o in orders:
        pn = o["purchase_no"]
        if pn in seen:
            prev = seen[pn]
            prev["order_qty"] = max(float(prev.get("order_qty") or 0), float(o.get("order_qty") or 0))
            prev["control_qty"] = max(
                float(prev.get("control_qty") or 0), float(o.get("control_qty") or 0)
            )
            continue
        item = {
            "purchase_no": pn,
            "order_qty": float(o.get("order_qty") or 0),
            "control_qty": float(o.get("control_qty") or 0),
        }
        seen[pn] = item
        out.append(item)
    return out


def _sanitize_qty(q: float) -> float:
    """修正 OCR 粘连数量（如 1500015000 → 15000）。"""
    try:
        q = float(q or 0)
    except (TypeError, ValueError):
        return 0.0
    if q <= 0:
        return 0.0
    if q < 100000:
        return q
    s = str(int(q))
    half = len(s) // 2
    if half and s[:half] == s[half : half * 2]:
        return float(s[:half])
    for cand in (100000, 50000, 20000, 15000, 10000, 5000, 2000, 1500, 1000, 500, 200, 100):
        if s.startswith(str(cand)):
            return float(cand)
    return q


def _fix_wo_qty(qty_str: str, rest: str) -> float:
    """纠正 compact 粘连：*6800112-100306 → 数量 6800 + 料号 112-100306。"""
    s = str(qty_str or "").strip()
    if not s:
        return 0.0
    if re.match(r"-\d{5,6}-\d{2}", rest or ""):
        for n in (3, 2, 4):
            if len(s) > n and s[:-n].isdigit() and s[-n:].isdigit():
                head = s[-n:]
                reconstituted = head + (rest or "")[:24]
                if re.match(rf"{re.escape(head)}-\d{{5,6}}-\d{{2}}", reconstituted):
                    return _sanitize_qty(float(s[:-n]))
    return _sanitize_qty(float(s))


def _merge_refdes_near_mats(chunk: str) -> str:
    """只采换料料号附近的位号，避免同块尾部扫进下一机型的位号。"""
    if not chunk:
        return ""
    parts: list[str] = []
    seen: set[str] = set()

    def _add_from(text: str) -> None:
        for tok in (_merge_refdes(text) or "").split(","):
            t = tok.strip().upper()
            if t and t not in seen:
                seen.add(t)
                parts.append(t)

    for m in _MAT_QTY.finditer(chunk):
        after = chunk[m.end() : m.end() + 120]
        cut = re.search(
            r"\d{4}-\d{8,}|(?:删除|增加)|(?:\d{3}-\d{5,6}-\d{2}[A-Za-z]?\s*[×xX*＊])",
            after,
        )
        if cut:
            after = after[: cut.start()]
        before = chunk[max(0, m.start() - 50) : m.start()]
        _add_from(after)
        _add_from(before)

    # OCR 常把后半位号拆到「第一张工单」后面：补采短窗，并截断说明段
    mats = list(_MAT_QTY.finditer(chunk))
    wos = list(re.finditer(r"\d{4}-\d{11,14}", chunk))
    if mats and wos:
        start = mats[0].start()
        end = min(len(chunk), wos[0].end() + 48)
        if len(wos) > 1:
            end = min(end, wos[1].start())
        region = chunk[start:end]
        mcut = re.search(r"PCBA管制|管制信息|成品料号|子件料号", region)
        wo_local = wos[0].start() - start
        if mcut and mcut.start() > wo_local:
            region = region[: mcut.start()]
        _add_from(region)

    if parts:
        return ",".join(parts)
    return _merge_refdes(chunk)


def _extract_change_from_chunk(
    chunk: str,
    shared_fallback: list[dict],
    refdes: str = "",
) -> list[dict]:
    """从机型块提取删/加料；位号优先用本块换料附近，禁止串到其他机型。"""
    local_ref = _merge_refdes_near_mats(chunk) or (refdes or "")
    mats = _MAT_QTY.findall(chunk)
    seen = set()
    pairs: list[tuple[str, float]] = []
    for code, qty in mats:
        key = (code, qty)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((_fix_part_code(code), float(qty)))
    if len(pairs) < 2:
        m = re.search(
            r"删除\s*(\d{3}-\d{5,6}-\d{2}[A-Za-z]?).{0,80}?"
            r"增加\s*(\d{3}-\d{5,6}-\d{2}[A-Za-z]?)",
            chunk,
            re.S,
        )
        if m:
            pairs = [(_fix_part_code(m.group(1)), 1.0), (_fix_part_code(m.group(2)), 1.0)]
            qm = re.search(r"数量\s*[:：]?\s*(\d+(?:\.\d+)?)", chunk)
            if qm:
                q = float(qm.group(1))
                pairs = [(pairs[0][0], q), (pairs[1][0], q)]
    if len(pairs) >= 2:
        out: list[dict] = []
        i = 0
        while i + 1 < len(pairs):
            rc, rq = pairs[i]
            ac, aq = pairs[i + 1]
            if rc == ac:
                i += 1
                continue
            out.append(
                {
                    "remove_code": rc,
                    "remove_qty": rq,
                    "remove_refdes": local_ref or None,
                    "add_code": ac,
                    "add_qty": aq or rq,
                    "add_refdes": local_ref or None,
                    "remark": None,
                }
            )
            i += 2
        if out:
            first = out[0]
            if all(
                c["remove_code"] == first["remove_code"] and c["add_code"] == first["add_code"]
                for c in out
            ):
                return [first]
            return out
    if not shared_fallback:
        return []
    patched = []
    for c in shared_fallback:
        item = dict(c)
        if local_ref:
            item["remove_refdes"] = local_ref
            item["add_refdes"] = local_ref
        patched.append(item)
    return patched


def _body_start(raw: str) -> int:
    for marker in ("成品料号信息", "管制料号", "工单号*数量", "工单号＊数量"):
        idx = raw.find(marker)
        if idx >= 0:
            return idx
    return 0


def _table_model_anchors(raw: str) -> list[tuple[str, int]]:
    """表格区内机型锚点（按首次出现顺序；跳过页眉「管制机型」枚举）。"""
    start = _body_start(raw)
    body = raw[start:]
    anchors: list[tuple[str, int]] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?:120|030)-\d{6}-\d{2}", body):
        mc = _fix_part_code(m.group(0))
        if mc in seen or mc.startswith("110-"):
            continue
        seen.add(mc)
        anchors.append((mc, start + m.start()))
    return anchors


def _build_model_groups(
    raw: str,
    compact: str,
    flat_orders: list[dict],
    shared_changes: list[dict],
    refdes: str,
) -> list[dict]:
    """按表格机型切块：工单/换料/位号只在本机型块内解析，禁止串组。"""
    anchors = _table_model_anchors(raw)
    if not anchors:
        # 退化：管制PCBA 段落
        sections = list(_PCBA_SECTION.finditer(raw))
        if sections:
            anchors = []
            for m in sections:
                mc = _fix_part_code(m.group(1))
                if not mc.startswith("110-"):
                    anchors.append((mc, m.start()))

    if not anchors:
        mc = _resolve_model_code(raw)
        return [
            {
                "model_code": mc or "UNKNOWN",
                "orders": _dedupe_orders(flat_orders),
                "changes": shared_changes or [],
            }
        ]

    # 每机型文本块：[本机型起, 下一机型起)
    chunks: list[tuple[str, str]] = []
    for i, (mc, pos) in enumerate(anchors):
        end = anchors[i + 1][1] if i + 1 < len(anchors) else len(raw)
        chunks.append((mc, raw[pos:end]))

    # 块内工单。OCR 常把「下一机型」的工单扫进上一机型块尾：仅溢出本块多扫到的工单。
    pending_wo: list[dict] = []
    model_orders: dict[str, list[dict]] = {mc: [] for mc, _ in chunks}
    claimed: set[str] = set()

    def _scan_wos(chunk: str) -> list[dict]:
        compact_chunk = re.sub(r"\s+", "", chunk)
        found: list[dict] = []
        for wm in _WO_FULL.finditer(compact_chunk):
            wo = _normalize_wo(wm.group(1))
            if wo in claimed:
                continue
            claimed.add(wo)
            qty = _fix_wo_qty(wm.group(2), compact_chunk[wm.end() :])
            found.append({"purchase_no": wo, "order_qty": qty, "control_qty": 0.0})
        for bm in _WO_BARE.finditer(compact_chunk):
            wo = _normalize_wo(bm.group(1))
            if wo in claimed:
                continue
            claimed.add(wo)
            found.append({"purchase_no": wo, "order_qty": 0.0, "control_qty": 0.0})
        for wm in _WO_ALPHA_FULL.finditer(compact_chunk):
            wo = _normalize_wo(wm.group(1))
            if wo in claimed:
                continue
            claimed.add(wo)
            found.append(
                {
                    "purchase_no": wo,
                    "order_qty": _sanitize_qty(float(wm.group(2))),
                    "control_qty": 0.0,
                }
            )
        for bm in _WO_ALPHA_BARE.finditer(compact_chunk):
            wo = _normalize_wo(bm.group(1))
            if wo in claimed:
                continue
            claimed.add(wo)
            found.append({"purchase_no": wo, "order_qty": 0.0, "control_qty": 0.0})
        return found

    for idx, (mc, chunk) in enumerate(chunks):
        local_wos = _scan_wos(chunk)
        incoming = pending_wo
        pending_wo = []
        # 仅当本块自己扫到 ≥2 个工单时，把第 2 个起交给下一机型（尾部错位）
        if idx + 1 < len(chunks) and len(local_wos) > 1:
            model_orders[mc] = incoming + local_wos[:1]
            pending_wo = local_wos[1:]
        else:
            model_orders[mc] = incoming + local_wos

    if pending_wo and chunks:
        last_mc = chunks[-1][0]
        have = {x["purchase_no"] for x in model_orders[last_mc]}
        for o in pending_wo:
            if o["purchase_no"] not in have:
                model_orders[last_mc].append(o)

    # 下一机型仍为空：说明溢出过度，按本块原文收回全部工单
    for i in range(len(chunks) - 1):
        mc, nxt = chunks[i][0], chunks[i + 1][0]
        if model_orders[nxt]:
            continue
        compact_chunk = re.sub(r"\s+", "", chunks[i][1])
        full: list[dict] = []
        seen_wo: set[str] = set()
        for wm in _WO_FULL.finditer(compact_chunk):
            wo = wm.group(1)
            if wo in seen_wo:
                continue
            seen_wo.add(wo)
            full.append(
                {
                    "purchase_no": wo,
                    "control_qty": _fix_wo_qty(wm.group(2), compact_chunk[wm.end() :]),
                }
            )
        model_orders[mc] = full

    groups: list[dict] = []
    for mc, chunk in chunks:
        ors = _dedupe_orders(model_orders.get(mc) or [])
        chs = _extract_change_from_chunk(chunk, shared_changes, "")
        if not ors:
            continue
        groups.append({"model_code": mc, "orders": ors, "changes": chs})
    return groups


def parse_control_text(text: str) -> dict:
    """从识别文本抽取管制单字段。"""
    warnings: list[str] = []
    raw = _normalize_text(text)
    compact = re.sub(r"\s+", "", raw)

    control_no = ""
    m = _CONTROL_NO.search(raw) or _CONTROL_NO.search(compact)
    if m:
        control_no = m.group(0).upper()

    model_code = _resolve_model_code(raw)

    ecn_no = ""
    em = _ECN.search(raw) or _ECN.search(compact)
    if em:
        ecn_no = em.group(0).upper()

    reason = ""
    rm = _REASON_NEAR.search(raw)
    if rm:
        reason = rm.group(1).strip(" 。.;；/：:")
        reason = re.sub(r"^主旨说明[：:]\s*", "", reason)
    elif "停产" in raw and "管制" in raw:
        # 截一段含停产的说明
        for line in raw.splitlines():
            if "停产" in line or "换料" in line or "改为" in line:
                reason = line.strip()[:120]
                break

    control_type = "PCBA管制"
    if "PCBA管制" in compact or "PCBA管制" in raw:
        control_type = "PCBA管制"

    # 表格分批行优先：每行「管制数量 + 一组换料」= 从工单总量中抽出的一批
    batch_changes = _extract_table_batch_changes(raw)
    table_batch_qty = 0.0
    if batch_changes:
        table_batch_qty = sum(float(c.get("control_qty") or 0) for c in batch_changes)

    # 工单号*数量里的数量 = 工单总量；表格 500 是本批管制，不能当总量
    orders: list[dict] = []
    full_prefix = None
    order_qty_from_wo = 0.0
    for wo, qty in _WO_FULL.findall(raw) + _WO_FULL.findall(compact):
        wo = _normalize_wo(wo)
        q = float(qty)
        # 若已有分批行，且 WO 数量恰好等于单批众数，多半是误把管制数量当成工单量
        if batch_changes and table_batch_qty and abs(q - float(batch_changes[0]["control_qty"])) < 0.1:
            orders.append({"purchase_no": wo, "order_qty": 0.0, "control_qty": 0.0})
        else:
            order_qty_from_wo = max(order_qty_from_wo, q)
            orders.append({"purchase_no": wo, "order_qty": q, "control_qty": 0.0})
        if len(wo) >= 12:
            full_prefix = wo[:-3]

    for wo, qty in _WO_ALPHA_FULL.findall(raw) + _WO_ALPHA_FULL.findall(compact):
        wo = _normalize_wo(wo)
        q = float(qty)
        order_qty_from_wo = max(order_qty_from_wo, q)
        orders.append({"purchase_no": wo, "order_qty": q, "control_qty": 0.0})

    # 无 * 数量的裸工单号（OCR 常把 * 吃掉或分行）
    for wo in _WO_BARE.findall(raw) + _WO_BARE.findall(compact):
        wo = _normalize_wo(wo)
        orders.append({"purchase_no": wo, "order_qty": 0.0, "control_qty": 0.0})
        if len(wo) >= 12:
            full_prefix = wo[:-3]

    for wo in _WO_ALPHA_BARE.findall(raw) + _WO_ALPHA_BARE.findall(compact):
        wo = _normalize_wo(wo)
        orders.append({"purchase_no": wo, "order_qty": 0.0, "control_qty": 0.0})

    # 整机工单号行
    for mwo in re.finditer(
        r"整机工单号\*数量[：:\s]*([A-Za-z]?\d{3,4}-\d{8,14})",
        raw,
        re.I,
    ):
        wo = _normalize_wo(mwo.group(1))
        orders.append({"purchase_no": wo, "order_qty": 0.0, "control_qty": 0.0})

    # 手写「工单号*数量」旁的大数量（如 *10000），勿吞进工单号尾段
    for m in re.finditer(
        r"(?:工单号\*数量|整机工单号\*数量)[：:\s]*([A-Za-z]?\d{3,4}-\d{8,14})\s*[×xX*＊]\s*(\d{3,8})",
        raw,
        re.I,
    ):
        q = float(m.group(2))
        if batch_changes and any(abs(q - float(c["control_qty"])) < 0.1 for c in batch_changes):
            continue
        order_qty_from_wo = max(order_qty_from_wo, q)
        wo = _normalize_wo(m.group(1))
        orders.append({"purchase_no": wo, "order_qty": q, "control_qty": 0.0})

    short_hits = _WO_SHORT.findall(raw) + _WO_SHORT.findall(compact)
    for short, qty in short_hits:
        if short in {"000", "100", "110", "111", "112", "118", "120", "030"}:
            continue
        qf = float(qty)
        if int(qf) in {110, 111, 112, 118, 120, 30} and qf == int(qf):
            continue
        orders.append({"purchase_no": short, "order_qty": qf, "control_qty": 0.0})
        order_qty_from_wo = max(order_qty_from_wo, qf)

    if full_prefix is None and orders:
        for o in orders:
            pn = o["purchase_no"]
            if len(pn) >= 12 and "-" in pn:
                full_prefix = pn[:-3]
                break

    orders = _expand_short_wos(orders, full_prefix)
    if full_prefix and orders:
        seqs = []
        for o in orders:
            pn = o["purchase_no"]
            if pn.startswith(full_prefix) and len(pn) == len(full_prefix) + 3:
                try:
                    seqs.append(int(pn[-3:]))
                except ValueError:
                    pass
        if seqs:
            lo, hi = min(seqs), max(seqs)
            if hi - lo <= 30:
                qty = order_qty_from_wo
                for n in range(lo, hi + 1):
                    pn = f"{full_prefix}{n:03d}"
                    if not any(o["purchase_no"] == pn for o in orders):
                        if re.search(
                            rf"(?:^|[^\d]){n:03d}\s*[×xX*＊]|(?:^|[^\d]){re.escape(pn)}(?:[^\d]|$)",
                            compact,
                        ):
                            orders.append(
                                {"purchase_no": pn, "order_qty": qty, "control_qty": 0.0}
                            )
                orders.sort(key=lambda x: x["purchase_no"])

    orders = _dedupe_orders(orders)
    orders = [o for o in orders if _is_wo_no(o["purchase_no"])]
    for o in orders:
        o["purchase_no"] = _normalize_wo(o["purchase_no"])
        if order_qty_from_wo and float(o.get("order_qty") or 0) <= 0:
            o["order_qty"] = order_qty_from_wo
        if "control_qty" not in o:
            o["control_qty"] = 0.0

    # —— 换料：优先表格分批行 ——
    refdes = _merge_refdes(raw) or _merge_refdes(compact)
    changes: list[dict] = []
    narr = _extract_narrative_changes(raw)

    if batch_changes:
        changes = batch_changes
        # 叙述位号可补表格 OCR 缺位
        for c in changes:
            for nc in narr:
                if nc["remove_code"] == c["remove_code"] and nc["add_code"] == c["add_code"]:
                    if not c.get("remove_refdes") and nc.get("remove_refdes"):
                        c["remove_refdes"] = nc["remove_refdes"]
                        c["add_refdes"] = nc.get("add_refdes") or nc["remove_refdes"]
                    break
        warnings.append(
            f"识别到 {len(changes)} 批分批管制（各批从工单总量中抽出，非整单都换料），请核对每批管制数量"
        )
    else:
        mat_pairs = _MAT_QTY.findall(raw) + _MAT_QTY.findall(compact)
        mats: list[tuple[str, float]] = []
        seen_m = set()
        for code, qty in mat_pairs:
            key = (code, qty)
            if key in seen_m:
                continue
            seen_m.add(key)
            mats.append((_fix_part_code(code), float(qty)))

        if len(mats) < 2:
            change_m = _CHANGE_SENTENCE.search(raw) or _CHANGE_SENTENCE.search(compact)
            if change_m:
                mats = [
                    (_fix_part_code(change_m.group(1)), 1.0),
                    (_fix_part_code(change_m.group(2)), 1.0),
                ]

        mats = [m for m in mats if m[0] != model_code]

        if len(mats) >= 2:
            i = 0
            while i + 1 < len(mats):
                remove_code, remove_qty = mats[i]
                add_code, add_qty = mats[i + 1]
                if remove_code == add_code:
                    i += 1
                    continue
                local_ref = _refdes_near_codes(raw, remove_code, add_code) or refdes
                for nc in narr:
                    if nc["remove_code"] == remove_code and nc["add_code"] == add_code:
                        if nc.get("remove_refdes"):
                            local_ref = nc["remove_refdes"]
                        break
                changes.append(
                    {
                        "control_qty": 0.0,
                        "remove_code": remove_code,
                        "remove_qty": remove_qty,
                        "remove_refdes": local_ref or None,
                        "add_code": add_code,
                        "add_qty": add_qty or remove_qty,
                        "add_refdes": local_ref or None,
                        "remark": None,
                    }
                )
                i += 2
            if len(changes) > 1:
                first = changes[0]
                same = all(
                    c["remove_code"] == first["remove_code"] and c["add_code"] == first["add_code"]
                    for c in changes
                )
                if same:
                    changes = [first]
        elif narr:
            for nc in narr:
                nc.setdefault("control_qty", 0.0)
            changes = narr
        elif len(mats) == 1:
            warnings.append("仅识别到一种料号，请手工补全换料对照")
            changes.append(
                {
                    "control_qty": 0.0,
                    "remove_code": mats[0][0],
                    "remove_qty": mats[0][1],
                    "remove_refdes": refdes or None,
                    "add_code": "",
                    "add_qty": 0,
                    "add_refdes": refdes or None,
                    "remark": None,
                }
            )

    # 工单行：合计管制数量 = 各批之和；总量保持 order_qty
    batch_sum = sum(float(c.get("control_qty") or 0) for c in changes)
    for o in orders:
        if batch_sum > 0:
            o["control_qty"] = batch_sum
        elif float(o.get("order_qty") or 0) > 0 and float(o.get("control_qty") or 0) <= 0:
            # 无分批信息时，默认整单管制
            o["control_qty"] = o["order_qty"]

    groups = _build_model_groups(raw, compact, orders, changes, refdes)
    # 过滤无工单空组
    groups = [g for g in groups if g.get("orders")]
    if not groups and (orders or changes):
        groups = [
            {
                "model_code": model_code or "UNKNOWN",
                "orders": orders,
                "changes": changes,
            }
        ]
    # 单组且机型仍空时回填
    for g in groups:
        if not g.get("model_code") or g["model_code"] == "UNKNOWN":
            if model_code:
                g["model_code"] = model_code
        if g.get("orders"):
            for o in g["orders"]:
                o.setdefault("order_qty", 0.0)
                o.setdefault("control_qty", 0.0)
                if batch_sum > 0 and float(o.get("control_qty") or 0) <= 0:
                    o["control_qty"] = batch_sum
                if order_qty_from_wo and float(o.get("order_qty") or 0) <= 0:
                    o["order_qty"] = order_qty_from_wo
        if not g.get("changes") and changes:
            g["changes"] = changes
        # 确保换料带 control_qty
        for c in g.get("changes") or []:
            c.setdefault("control_qty", 0.0)
    model_summary = "、".join(g["model_code"] for g in groups if g.get("model_code"))
    flat_orders = []
    for g in groups:
        flat_orders.extend(g.get("orders") or [])
    flat_orders = _dedupe_orders([o for o in flat_orders if o.get("purchase_no")])

    if batch_sum > 0 and order_qty_from_wo <= 0:
        warnings.append(
            "未识别到工单总量（如图上手写 *10000），请手工填写；本批管制数量已按表格分行识别"
        )
    if not control_no:
        warnings.append("未识别到管制单号，请核对后填写")
    if not groups:
        warnings.append("未识别到机型/工单，请核对后填写")
    elif len(groups) > 1:
        warnings.append(f"识别到 {len(groups)} 个机型分组，请核对各组工单与换料")
    if model_code and not re.match(r"^\d{3}-", model_code):
        warnings.append(f"机型识别为产品型号「{model_code}」，请核对是否需改为 PCBA 料号")
    if not any(g.get("changes") for g in groups):
        warnings.append("未识别到换料明细，请手工填写")
    if not any(g.get("orders") for g in groups):
        warnings.append("未识别到工单号，请手工补全")
    if not refdes and any(g.get("changes") for g in groups):
        warnings.append("位号可能为手写，识别不全时请手工补全")

    fields = {
        "control_no": control_no,
        "model_code": model_summary or model_code,
        "control_type": control_type,
        "reason": reason or None,
        "ecn_no": ecn_no or None,
        "groups": groups,
        # 兼容旧前端
        "orders": flat_orders,
        "changes": (groups[0].get("changes") if groups else changes) or [],
    }
    return {
        "fields": fields,
        "warnings": warnings,
        "raw_text_preview": raw[:2000],
    }


def parse_control_file(filename: str, data: bytes) -> dict:
    if not data:
        raise ValueError("空文件")
    if len(data) > 30 * 1024 * 1024:
        raise ValueError("附件过大（上限 30MB）")
    text, source = extract_text_from_file(filename, data)
    if not text.strip():
        raise ValueError("未能从文件中识别到文字，请改用更清晰扫描件或手工填写")
    result = parse_control_text(text)
    result["source"] = source
    if source == "ocr":
        result["warnings"] = [
            "已通过 OCR 识别，结果仅供预填，请务必人工核对后再保存/确认",
            *result["warnings"],
        ]
    else:
        result["warnings"] = [
            "识别结果仅供预填，请务必人工核对后再保存/确认",
            *result["warnings"],
        ]
    return result
