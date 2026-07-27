"""订单报价计价引擎（与鼎雄报价单习惯填法对齐）"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


# 默认费率（与 120-200352-05 报价单一致）
DEFAULT_RATES = {
    "chip_point": 0.0095,
    "chip2_factor": 1.5,
    "ic_point": 0.02,
    "odd_point": 0.02,
    "bigpad": 0.065,
    "dip_point": 0.045,
    "tangxi": 1.5,
    "wave_fixture_unit": 400.0,
    "stencil_unit": 400.0,
}


@dataclass
class BomInputLine:
    seq: str = ""
    material_code: str = ""
    material_name: str = ""
    spec: str = ""
    qty_per: float = 0
    unit: str = "PCS"
    position: str = ""
    ic_amount: float = 0.0  # P
    dip_points: float = 0.0  # Q


@dataclass
class ClassifiedBomLine:
    seq: str
    material_code: str
    material_name: str
    spec: str
    qty_per: float
    unit: str
    position: str
    package: str
    bucket: str
    ic_amount: float
    dip_points: float
    calc_points: float
    calc_amount: float


@dataclass
class CostLineDraft:
    section: str
    item_key: str
    item_name: str
    qty: float
    points: float
    unit_price: float
    unit: str
    amount: float
    note: str = ""
    editable: bool = False
    sort_order: int = 0


@dataclass
class QuoteCalcResult:
    bom_lines: list[ClassifiedBomLine] = field(default_factory=list)
    cost_lines: list[CostLineDraft] = field(default_factory=list)
    unit_price: float = 0.0
    tooling_total: float = 0.0
    engineering_fee: float = 0.0
    summary: dict[str, Any] = field(default_factory=dict)


def detect_package(spec: str, name: str = "") -> str:
    s = f"{spec} {name}".upper()
    rules = [
        ("2512", r"2512"),
        ("1210", r"1210"),
        ("1206", r"1206"),
        ("0805", r"0805"),
        ("0603", r"0603"),
        ("0402", r"0402"),
        ("TQFP-48", r"TQFP-?48"),
        ("SOIC-16", r"SOIC-?16"),
        ("SOIC-14", r"SOIC-?14"),
        ("SOIC-8", r"SOIC-?8"),
        ("SO-4", r"SO-?4"),
        ("PowerPAD", r"POWERPAD"),
        ("DUB-8", r"DUB-?8"),
        ("TO-263", r"TO-?263"),
        ("TO-252", r"TO-?252"),
        ("SOT-223", r"SOT-?223"),
        ("SOT-89", r"SOT-?89"),
        ("SOT-23", r"SOT-?23"),
        ("SMA", r"\bSMA\b"),
        ("SMC", r"\bSMC\b"),
        ("SOD-123", r"SOD-?123"),
        ("SMD-ECAP", r"铝电解|CAL,|SMD-ECAP|EMK1"),
        ("电感CD54", r"HXCD54"),
        ("SOT类", r"2SC4672|AB3"),
    ]
    for lab, pat in rules:
        if re.search(pat, s, re.I):
            return lab
    return "其他"


def classify_and_price(
    lines: list[BomInputLine],
    *,
    rates: Optional[dict[str, float]] = None,
    tangxi: Optional[float] = None,
    stencil_qty: float = 1,
    wave_fixture_qty: float = 0,
    post_extra: Optional[list[CostLineDraft]] = None,
) -> QuoteCalcResult:
    """
    习惯填法：
    - DIP：Q 列有值 → dip，点数=Q，单价 dip_point
    - 光板/排线 → skip
    - P 列有值 → ic，金额直接用 P
    - TO-263 → bigpad × 0.065
    - 0603/1206 → chip1，1点×0.0095
    - 其余贴片 → chip2，1.5点×0.0095
    - 异形/IC一 = 0
    - 塘锡默认 1.5（可覆盖）
    """
    r = {**DEFAULT_RATES, **(rates or {})}
    chip_rate = float(r["chip_point"])
    chip2_factor = float(r["chip2_factor"])
    bigpad_rate = float(r["bigpad"])
    dip_rate = float(r["dip_point"])
    tangxi_amt = float(r["tangxi"] if tangxi is None else tangxi)

    classified: list[ClassifiedBomLine] = []
    chip1_qty = chip2_qty = bigpad_qty = 0.0
    ic_money = dip_pts = 0.0

    for row in lines:
        qty = float(row.qty_per or 0)
        if qty <= 0:
            continue
        name = (row.material_name or "").strip()
        spec = (row.spec or "").strip()
        pkg = detect_package(spec, name)
        ic_amt = float(row.ic_amount or 0)
        dip_p = float(row.dip_points or 0)

        if dip_p:
            bucket = "dip"
            pts = dip_p
            amt = dip_p * dip_rate
            dip_pts += dip_p
        elif any(k in name for k in ("光板", "排线")):
            bucket = "skip"
            pts = amt = 0.0
        elif ic_amt:
            bucket = "ic"
            pts = 0.0
            amt = ic_amt
            ic_money += ic_amt
        elif pkg == "TO-263":
            bucket = "bigpad"
            pts = 0.0
            amt = qty * bigpad_rate
            bigpad_qty += qty
        elif pkg in {"0603", "1206"}:
            bucket = "chip1"
            pts = qty * 1.0
            amt = pts * chip_rate
            chip1_qty += qty
        else:
            bucket = "chip2"
            pts = qty * chip2_factor
            amt = pts * chip_rate
            chip2_qty += qty

        classified.append(
            ClassifiedBomLine(
                seq=row.seq or "",
                material_code=row.material_code or "",
                material_name=name,
                spec=spec,
                qty_per=qty,
                unit=row.unit or "PCS",
                position=row.position or "",
                package=pkg,
                bucket=bucket,
                ic_amount=ic_amt,
                dip_points=dip_p,
                calc_points=pts,
                calc_amount=round(amt, 6),
            )
        )

    chip1_pts = chip1_qty * 1.0
    chip2_pts = chip2_qty * chip2_factor
    chip1_amt = chip1_pts * chip_rate
    chip2_amt = chip2_pts * chip_rate
    bigpad_amt = bigpad_qty * bigpad_rate
    dip_amt = dip_pts * dip_rate
    smt_sub = chip1_amt + chip2_amt + ic_money + bigpad_amt + tangxi_amt
    dip_sub = dip_amt

    costs: list[CostLineDraft] = []
    order = 0

    def add(**kwargs):
        nonlocal order
        order += 10
        costs.append(CostLineDraft(sort_order=order, **kwargs))

    add(
        section="smt",
        item_key="chip1",
        item_name="CHIP件一类",
        qty=chip1_qty,
        points=chip1_pts,
        unit_price=chip_rate,
        unit="点",
        amount=round(chip1_amt, 6),
        note="0603/1206，1颗=1点",
    )
    add(
        section="smt",
        item_key="chip2",
        item_name="CHIP件二类",
        qty=chip2_qty,
        points=chip2_pts,
        unit_price=chip_rate,
        unit="点",
        amount=round(chip2_amt, 6),
        note=f"其余贴片，1颗={chip2_factor}点",
    )
    add(
        section="smt",
        item_key="odd",
        item_name="异形器件",
        qty=0,
        points=0,
        unit_price=float(r["odd_point"]),
        unit="点",
        amount=0,
        note="习惯填法本行不用",
    )
    add(
        section="smt",
        item_key="ic1",
        item_name="IC件一（≤8pin）",
        qty=0,
        points=0,
        unit_price=float(r["ic_point"]),
        unit="点",
        amount=0,
        note="习惯填法并入IC二",
    )
    add(
        section="smt",
        item_key="ic2",
        item_name="IC件二（＞8pin）",
        qty=0,
        points=0,
        unit_price=float(r["ic_point"]),
        unit="点",
        amount=round(ic_money, 6),
        note="BOM 的 P 列金额合计",
    )
    add(
        section="smt",
        item_key="bigpad",
        item_name="大焊盘器件",
        qty=bigpad_qty,
        points=bigpad_qty,
        unit_price=bigpad_rate,
        unit="PCS",
        amount=round(bigpad_amt, 6),
        note="TO-263 功率管",
    )
    add(
        section="smt",
        item_key="tangxi",
        item_name="塘锡道上锡",
        qty=0,
        points=0,
        unit_price=1,
        unit="PCS",
        amount=round(tangxi_amt, 6),
        note="可手工调整",
        editable=True,
    )
    add(
        section="smt",
        item_key="smt_subtotal",
        item_name="SMT小计",
        qty=chip1_qty + chip2_qty,
        points=chip1_pts + chip2_pts,
        unit_price=0,
        unit="",
        amount=round(smt_sub, 6),
        note="",
    )

    add(
        section="dip",
        item_key="dip2",
        item_name="插件器件二",
        qty=0,
        points=dip_pts,
        unit_price=dip_rate,
        unit="点",
        amount=round(dip_amt, 6),
        note="Q 列脚数当点",
    )
    add(
        section="dip",
        item_key="dip_subtotal",
        item_name="插件小计",
        qty=0,
        points=dip_pts,
        unit_price=0,
        unit="",
        amount=round(dip_sub, 6),
        note="",
    )

    post_amount = 0.0
    for extra in post_extra or []:
        order += 10
        extra.sort_order = order
        costs.append(extra)
        if extra.section == "post" and "subtotal" not in extra.item_key:
            post_amount += float(extra.amount or 0)

    if not post_extra:
        add(
            section="post",
            item_key="post_subtotal",
            item_name="后加工小计",
            qty=0,
            points=0,
            unit_price=0,
            unit="",
            amount=0,
            note="可后续补录三防/测试等",
            editable=True,
        )

    unit_price = round(smt_sub + dip_sub + post_amount, 6)

    stencil_amt = float(stencil_qty) * float(r["stencil_unit"])
    wave_amt = float(wave_fixture_qty) * float(r["wave_fixture_unit"])
    tooling = round(stencil_amt + wave_amt, 6)
    add(
        section="tooling",
        item_key="stencil",
        item_name="SMT 钢网",
        qty=stencil_qty,
        points=stencil_qty,
        unit_price=float(r["stencil_unit"]),
        unit="PCS",
        amount=stencil_amt,
        note="按供应商实际报价",
        editable=True,
    )
    add(
        section="tooling",
        item_key="wave_fixture",
        item_name="波峰焊治具",
        qty=wave_fixture_qty,
        points=wave_fixture_qty,
        unit_price=float(r["wave_fixture_unit"]),
        unit="PCS",
        amount=wave_amt,
        note="按供应商实际报价",
        editable=True,
    )
    add(
        section="tooling",
        item_key="tooling_subtotal",
        item_name="专用治具合计",
        qty=0,
        points=0,
        unit_price=0,
        unit="",
        amount=tooling,
        note="",
    )
    add(
        section="summary",
        item_key="unit_price",
        item_name="产品加工含税单价",
        qty=1,
        points=0,
        unit_price=unit_price,
        unit="RMB",
        amount=unit_price,
        note="SMT+DIP+后加工",
    )

    return QuoteCalcResult(
        bom_lines=classified,
        cost_lines=costs,
        unit_price=unit_price,
        tooling_total=tooling,
        engineering_fee=0,
        summary={
            "chip1_qty": chip1_qty,
            "chip2_qty": chip2_qty,
            "chip1_points": chip1_pts,
            "chip2_points": chip2_pts,
            "ic_amount": ic_money,
            "bigpad_qty": bigpad_qty,
            "dip_points": dip_pts,
            "smt_subtotal": round(smt_sub, 6),
            "dip_subtotal": round(dip_sub, 6),
            "post_subtotal": round(post_amount, 6),
            "tangxi": tangxi_amt,
        },
    )
