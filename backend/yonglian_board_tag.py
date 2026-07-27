"""永联替代表板别（D1/U1/U2/U3/M1/结构）与机型品名匹配。"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

BOARD_TAGS = ("D1", "U1", "U2", "U3", "M1", "结构")

# 品名末段常见形态：CZU1 / SU3板 / SM1板 / SD1_PCBA
_TAG_IN_NAME = re.compile(
    r"(?:CZ|S)?(?P<tag>D1|U[123]|M1)(?:板|_?PCBA|-PCBA|$)",
    re.IGNORECASE,
)


def extract_board_tag(name: Optional[str]) -> str:
    """从机型品名/规格中提取板别代号。"""
    text = (name or "").strip()
    if not text:
        return ""
    if "结构" in text:
        return "结构"
    m = _TAG_IN_NAME.search(text)
    if m:
        return m.group("tag").upper()
    upper = text.upper()
    for tag in ("U3", "U2", "U1", "M1", "D1"):
        if tag in upper:
            return tag
    return ""


def match_bom_for_board_tag(
    db: Session,
    *,
    customer_id: str = "yonglian",
    purchase_no: str = "",
    board_tag: str,
):
    """在同客户（优先同订单）bom_models 中按品名板别找机型。"""
    from models import BomModel

    tag = (board_tag or "").strip()
    if not tag:
        return None
    cid = (customer_id or "yonglian").strip() or "yonglian"
    pn = (purchase_no or "").strip()

    q = db.query(BomModel).filter(
        BomModel.customer_id == cid,
        BomModel.is_active.is_(True),
    )
    pool = q.filter(BomModel.purchase_no == pn).all() if pn else []
    if not pool:
        pool = q.all()

    hits = [
        bom
        for bom in pool
        if extract_board_tag(bom.model_name) == tag or extract_board_tag(bom.model_spec) == tag
    ]
    if not hits:
        return None
    return hits[0]
