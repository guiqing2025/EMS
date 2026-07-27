"""PCBA 条码解析：

- 菲利斯等镭雕：D0 + 机型6位 + 版本2位 + 日期YYMMDD + 流水5位
- 恩玖人工贴码：16 位数字
  固定2 + 物料4 + 供应商2 + 年周4 + 流水4
"""
from __future__ import annotations

import re
from typing import Optional

BARCODE_RE = re.compile(r"^D[S0]([0-9A-Z]{6})(\d{2})(\d{6})(\d{5})$", re.I)
# 恩玖 DIP 人工贴码：16 位数字（常见以 0 开头，亦有 91… 等）
ENJIU_BARCODE_RE = re.compile(r"^\d{16}$")
MODEL_RE = re.compile(r"^(\d+)-([0-9A-Za-z]{6,8})-(\d{1,2})$")


def split_model_code(model_code: str) -> tuple[str, str, str]:
    """120-200235-09 → (prefix, mid, ver)。版本不足 2 位时左侧补 0。"""
    text = (model_code or "").strip()
    m = MODEL_RE.match(text)
    if m:
        mid = m.group(2).upper()
        ver = m.group(3).zfill(2)
        if len(mid) > 6:
            mid = mid[-6:]
        return m.group(1), mid, ver
    parts = text.split("-")
    if len(parts) >= 3:
        mid = parts[-2].upper()
        ver = parts[-1].zfill(2)
        if re.fullmatch(r"[0-9A-Z]{6,8}", mid) and re.fullmatch(r"\d{2}", ver):
            if len(mid) > 6:
                mid = mid[-6:]
            return parts[0], mid, ver
    raise ValueError(f"机型号格式应为 120-XXXXXX-XX，当前：{text}")


def build_model_code(prefix: str, mid: str, ver: str) -> str:
    return f"{prefix}-{mid}-{ver}"


def is_enjiu_barcode(barcode: str) -> bool:
    text = re.sub(r"\s+", "", (barcode or "").strip())
    if not ENJIU_BARCODE_RE.match(text):
        return False
    # 排除菲利斯 D0 形态（不应出现纯数字 D0…）；恩玖为纯数字 16 位
    return not text.upper().startswith("D0")


def parse_enjiu_barcode(barcode: str) -> Optional[dict]:
    """恩玖人工贴码：02|9413|11|2450|1021 → 固定/物料/供应商/年周/流水。"""
    text = re.sub(r"\s+", "", (barcode or "").strip())
    if not ENJIU_BARCODE_RE.match(text):
        return None
    fixed = text[0:2]
    material = text[2:6]
    supplier = text[6:8]
    year_week = text[8:12]
    seq = int(text[12:16])
    prefix12 = text[0:12]
    return {
        "barcode": text,
        "kind": "enjiu_manual",
        "barcode_prefix": prefix12,
        "fixed_code": fixed,
        "material_no": material,
        "supplier_code": supplier,
        "year_week": year_week,
        "model_mid": prefix12[:6],
        "model_ver": None,
        "laser_date": None,
        "seq": seq,
        # 常见 03xxxxxx 机型可由 03+后6 位猜测；91 开头等以登记表机型为准
        "model_code_guess": f"03{prefix12[:6]}" if fixed == "02" else prefix12[:8],
    }


def parse_pcba_barcode(barcode: str) -> Optional[dict]:
    raw = (barcode or "").strip()
    text = raw.upper()
    # 扫码枪/手输常把前缀数字 0 误成字母 O（DO… → D0…）
    if text.startswith("DO") and len(text) > 2 and text[2].isdigit():
        text = "D0" + text[2:]
    m = BARCODE_RE.match(text)
    if m:
        mid, ver, laser_date, seq_s = m.group(1), m.group(2), m.group(3), m.group(4)
        # 保留原始前缀形态（D0 / DS），便于溯源；匹配仍按 mid/ver/date/seq
        prefix = text[:2]
        return {
            "barcode": text,
            "kind": "laser_d0",
            "prefix": prefix,
            "model_mid": mid,
            "model_ver": ver,
            "laser_date": laser_date,
            "seq": int(seq_s),
            "model_code_guess": f"120-{mid}-{ver}",
        }
    # 恩玖保持原始数字大小写（全为数字）
    enjiu = parse_enjiu_barcode(raw)
    if enjiu:
        return enjiu
    return None


def normalize_yymmdd(value) -> str:
    if value is None:
        raise ValueError("日期不能为空")
    if isinstance(value, int):
        text = f"{value:06d}"
    else:
        text = str(value).strip().replace("-", "").replace("/", "")
        text = text.replace(".", "")
    if len(text) == 8 and text.startswith("20"):
        text = text[2:]
    if not re.fullmatch(r"\d{6}", text):
        raise ValueError(f"日期应为 YYMMDD：{value}")
    return text
