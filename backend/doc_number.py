"""单据编号规则：前缀 + 日期 + 流水（阶段 0）"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from models import DocNumberSeq

# 流程图主单据类型 → 前缀 / 中文名
DOC_TYPE_DEFAULTS: list[tuple[str, str, str]] = [
    ("inquiry", "XJ", "询价单"),
    ("cost_quote", "CB", "成本报价"),
    ("quotation", "BJ", "报价单"),
    ("sample_order", "DY", "打样订单"),
    ("sales_order", "SO", "销售订单"),
    ("stock_order", "BH", "备货单"),
    ("sample_loan", "JY", "借样单"),
    ("mrp_run", "MRP", "MRP运算"),
    ("customer_forecast", "YGC", "客户预告"),
    ("purchase_forecast", "YGP", "采购预告"),
    ("purchase_plan", "CGJ", "采购计划"),
    ("production_plan", "SCJ", "生产计划"),
    ("outsource_plan", "WWJ", "委外计划"),
    ("purchase_order", "PO", "采购单"),
    ("purchase_inspect", "CGSJ", "采购入库送检单"),
    ("purchase_receipt", "CGRK", "采购入库单"),
    ("purchase_return", "CGTH", "采购退货单"),
    ("production_order", "MO", "生产单"),
    ("production_qa", "QA", "生产QA检验单"),
    ("material_issue", "LL", "生产领料单"),
    ("material_supplement", "BL", "生产补料单"),
    ("material_return", "TL", "生产退料单"),
    ("fg_receipt", "CPRK", "成品入库单"),
    ("outsource_order", "WW", "委外单"),
    ("outsource_ship", "WWFL", "委外发料单"),
    ("outsource_inspect", "WWSJ", "委外入库送检单"),
    ("outsource_receipt", "WWRK", "委托入库单"),
    ("outsource_return", "WWTH", "委外退货单"),
    ("sales_issue", "XSCK", "销售出库单"),
    ("delivery_note", "FH", "发货单"),
    ("sales_return", "XSTH", "销售出库退货单"),
    ("complaint", "TS", "投诉单"),
    ("stocktake", "PD", "库存盘点"),
    ("transfer", "DB", "库存调拨单"),
    ("inventory_out", "CK", "库存出库单"),
    ("payment_request", "FKSQ", "付款申请单"),
    ("payment", "FK", "付款单"),
    ("receipt", "SK", "收款单"),
    ("other_expense", "QTFY", "其他费用支出"),
    ("other_income", "QTSR", "其他费用收入"),
    ("invoice_reg", "FP", "发票登记"),
    ("fin_bill", "PJ", "票据登记"),
    ("gl_voucher", "JZ", "记账凭证"),
    ("fixed_asset", "GZ", "固定资产"),
]


def ensure_doc_number_defaults(db: Session) -> int:
    n = 0
    for doc_type, prefix, name in DOC_TYPE_DEFAULTS:
        row = db.query(DocNumberSeq).filter(DocNumberSeq.doc_type == doc_type).first()
        if row:
            continue
        db.add(
            DocNumberSeq(
                doc_type=doc_type,
                prefix=prefix,
                name=name,
                date_fmt="%Y%m%d",
                seq_width=4,
                last_date="",
                last_seq=0,
            )
        )
        n += 1
    if n:
        db.flush()
    return n


def next_doc_number(db: Session, doc_type: str, *, when: datetime | None = None) -> str:
    """生成下一单号；同日流水递增，跨日重置。"""
    ensure_doc_number_defaults(db)
    row = db.query(DocNumberSeq).filter(DocNumberSeq.doc_type == doc_type).first()
    if not row:
        raise ValueError(f"未知单据类型：{doc_type}")
    now = when or datetime.now()
    try:
        date_part = now.strftime(row.date_fmt or "%Y%m%d")
    except Exception:
        date_part = now.strftime("%Y%m%d")
    if row.last_date != date_part:
        row.last_date = date_part
        row.last_seq = 1
    else:
        row.last_seq = int(row.last_seq or 0) + 1
    row.updated_at = datetime.utcnow()
    width = max(3, int(row.seq_width or 4))
    return f"{row.prefix}{date_part}{row.last_seq:0{width}d}"


def peek_doc_number(db: Session, doc_type: str, *, when: datetime | None = None) -> str:
    """预览下一单号（不占用流水）。"""
    ensure_doc_number_defaults(db)
    row = db.query(DocNumberSeq).filter(DocNumberSeq.doc_type == doc_type).first()
    if not row:
        raise ValueError(f"未知单据类型：{doc_type}")
    now = when or datetime.now()
    try:
        date_part = now.strftime(row.date_fmt or "%Y%m%d")
    except Exception:
        date_part = now.strftime("%Y%m%d")
    if row.last_date != date_part:
        seq = 1
    else:
        seq = int(row.last_seq or 0) + 1
    width = max(3, int(row.seq_width or 4))
    return f"{row.prefix}{date_part}{seq:0{width}d}"


def get_doc_number_rule(db: Session, doc_type: str) -> DocNumberSeq:
    ensure_doc_number_defaults(db)
    row = db.query(DocNumberSeq).filter(DocNumberSeq.doc_type == doc_type).first()
    if not row:
        raise ValueError(f"未知单据类型：{doc_type}")
    return row


def update_doc_number_rule(
    db: Session,
    doc_type: str,
    *,
    prefix: str | None = None,
    name: str | None = None,
    date_fmt: str | None = None,
    seq_width: int | None = None,
) -> DocNumberSeq:
    row = get_doc_number_rule(db, doc_type)
    if prefix is not None:
        p = prefix.strip().upper()
        if not p or len(p) > 16:
            raise ValueError("前缀不能为空且最长 16 位")
        if not p.isalnum():
            raise ValueError("前缀仅支持字母和数字")
        row.prefix = p
    if name is not None:
        row.name = (name or "").strip()[:64]
    if date_fmt is not None:
        fmt = (date_fmt or "").strip() or "%Y%m%d"
        try:
            datetime.now().strftime(fmt)
        except Exception as exc:
            raise ValueError("日期格式无效") from exc
        row.date_fmt = fmt
    if seq_width is not None:
        w = int(seq_width)
        if w < 3 or w > 8:
            raise ValueError("流水位数需在 3～8 之间")
        row.seq_width = w
    row.updated_at = datetime.utcnow()
    return row


def list_doc_number_rules(db: Session) -> list[DocNumberSeq]:
    ensure_doc_number_defaults(db)
    return db.query(DocNumberSeq).order_by(DocNumberSeq.doc_type).all()


def rule_to_dict(row: DocNumberSeq) -> dict:
    return {
        "doc_type": row.doc_type,
        "prefix": row.prefix,
        "name": row.name,
        "date_fmt": row.date_fmt,
        "seq_width": row.seq_width,
        "last_date": row.last_date or "",
        "last_seq": int(row.last_seq or 0),
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
