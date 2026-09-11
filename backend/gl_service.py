"""阶段10：总账 — 科目/期间/凭证审核过账/业务自动凭证/损益结转关账/固资折旧简版"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from doc_number import next_doc_number
from models import FixedAsset, GlAccount, GlPeriod, GlVoucher, GlVoucherLine

# 精简科目种子：(code, name, category, balance_dir)
SEED_ACCOUNTS: list[tuple[str, str, str, str]] = [
    ("1001", "库存现金", "asset", "debit"),
    ("1002", "银行存款", "asset", "debit"),
    ("1122", "应收账款", "asset", "debit"),
    ("1403", "原材料", "asset", "debit"),
    ("1405", "库存商品", "asset", "debit"),
    ("1601", "固定资产", "asset", "debit"),
    ("1602", "累计折旧", "asset", "credit"),
    ("2202", "应付账款", "liability", "credit"),
    ("4001", "实收资本", "equity", "credit"),
    ("4103", "本年利润", "equity", "credit"),
    ("5001", "生产成本", "cost", "debit"),
    ("5101", "制造费用", "cost", "debit"),
    ("6001", "主营业务收入", "income", "credit"),
    ("6401", "主营业务成本", "expense", "debit"),
    ("6602", "管理费用", "expense", "debit"),
]


def _now() -> datetime:
    return datetime.utcnow()


def _period_str(when: Optional[datetime] = None) -> str:
    return (when or _now()).strftime("%Y%m")


def ensure_gl_seed(db: Session, *, opening: bool = True) -> dict:
    """种子科目 + 当前期间；可选期初开账凭证。"""
    for code, name, cat, direction in SEED_ACCOUNTS:
        row = db.query(GlAccount).filter(GlAccount.code == code).first()
        if not row:
            db.add(
                GlAccount(
                    code=code,
                    name=name,
                    category=cat,
                    balance_dir=direction,
                    is_active=True,
                    balance=0,
                )
            )
    db.flush()
    period = _period_str()
    p = db.query(GlPeriod).filter(GlPeriod.period == period).first()
    if not p:
        p = GlPeriod(period=period, status="open", opened_at=_now(), remark="自动开账期间")
        db.add(p)
        db.flush()
    opening_voucher = None
    if opening:
        # 若尚无任何过账凭证，生成期初：借银行存款 / 贷实收资本
        posted = db.query(GlVoucher).filter(GlVoucher.status == "posted").count()
        if posted == 0 and not db.query(GlVoucher).filter(GlVoucher.source_type == "opening").first():
            opening_voucher = create_voucher(
                db,
                {
                    "period": period,
                    "source_type": "opening",
                    "source_no": "OPENING",
                    "summary": "期初开账",
                    "lines": [
                        {"account_code": "1002", "debit": 100000, "credit": 0, "summary": "期初银行存款"},
                        {"account_code": "4001", "debit": 0, "credit": 100000, "summary": "期初实收资本"},
                    ],
                },
                user="system",
            )
            review_voucher(db, opening_voucher.id, user="system")
            post_voucher(db, opening_voucher.id, user="system")
    return {"period": period, "opening_voucher_id": opening_voucher.id if opening_voucher else None}


def get_open_period(db: Session) -> GlPeriod:
    ensure_gl_seed(db, opening=False)
    period = _period_str()
    p = db.query(GlPeriod).filter(GlPeriod.period == period).first()
    if not p:
        p = GlPeriod(period=period, status="open", opened_at=_now())
        db.add(p)
        db.flush()
    if p.status == "closed":
        raise ValueError(f"会计期间 {p.period} 已关账，不可记账")
    return p


def account_to_dict(row: GlAccount) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "category": row.category,
        "balance_dir": row.balance_dir,
        "balance": row.balance,
        "is_active": bool(row.is_active),
    }


def list_accounts(db: Session) -> list[GlAccount]:
    ensure_gl_seed(db, opening=False)
    return db.query(GlAccount).filter(GlAccount.is_active.is_(True)).order_by(GlAccount.code).all()


def voucher_to_dict(row: GlVoucher, lines: list[GlVoucherLine] | None = None) -> dict:
    d = {
        "id": row.id,
        "voucher_no": row.voucher_no,
        "period": row.period,
        "status": row.status,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_no": row.source_no,
        "summary": row.summary,
        "created_by": row.created_by,
        "reviewed_by": row.reviewed_by,
        "posted_by": row.posted_by,
        "posted_at": row.posted_at,
        "created_at": row.created_at,
    }
    if lines is not None:
        d["lines"] = [
            {
                "id": ln.id,
                "account_code": ln.account_code,
                "account_name": ln.account_name,
                "debit": ln.debit,
                "credit": ln.credit,
                "summary": ln.summary,
            }
            for ln in lines
        ]
        d["total_debit"] = round(sum(float(ln.debit or 0) for ln in lines), 4)
        d["total_credit"] = round(sum(float(ln.credit or 0) for ln in lines), 4)
    return d


def get_voucher(db: Session, vid: int) -> tuple[GlVoucher, list[GlVoucherLine]]:
    row = db.query(GlVoucher).filter(GlVoucher.id == vid).first()
    if not row:
        raise ValueError("凭证不存在")
    lines = (
        db.query(GlVoucherLine)
        .filter(GlVoucherLine.voucher_id == vid)
        .order_by(GlVoucherLine.sort_order, GlVoucherLine.id)
        .all()
    )
    return row, lines


def list_vouchers(db: Session, *, period: str = "", status: str = "", limit: int = 100) -> list[GlVoucher]:
    q = db.query(GlVoucher)
    if period.strip():
        q = q.filter(GlVoucher.period == period.strip())
    if status.strip():
        q = q.filter(GlVoucher.status == status.strip())
    return q.order_by(GlVoucher.id.desc()).limit(limit).all()


def create_voucher(db: Session, data: dict, *, user: str) -> GlVoucher:
    period = (data.get("period") or "").strip() or get_open_period(db).period
    p = db.query(GlPeriod).filter(GlPeriod.period == period).first()
    if p and p.status == "closed":
        raise ValueError(f"期间 {period} 已关账")
    lines = data.get("lines") or []
    if len(lines) < 2:
        raise ValueError("凭证至少两行")
    total_d = total_c = 0.0
    resolved = []
    for i, raw in enumerate(lines):
        code = (raw.get("account_code") or "").strip()
        acc = db.query(GlAccount).filter(GlAccount.code == code).first()
        if not acc:
            raise ValueError(f"科目不存在：{code}")
        debit = float(raw.get("debit") or 0)
        credit = float(raw.get("credit") or 0)
        if debit < 0 or credit < 0 or (debit > 0 and credit > 0):
            raise ValueError(f"{code} 借贷金额非法")
        if debit == 0 and credit == 0:
            raise ValueError(f"{code} 借贷不能同时为 0")
        total_d += debit
        total_c += credit
        resolved.append((acc, debit, credit, (raw.get("summary") or "").strip(), i))
    if round(total_d, 4) != round(total_c, 4):
        raise ValueError(f"借贷不平衡：借 {total_d} / 贷 {total_c}")
    source_type = (data.get("source_type") or "manual").strip() or "manual"
    source_id = data.get("source_id")
    if source_type != "manual" and source_id is not None:
        exists = (
            db.query(GlVoucher)
            .filter(
                GlVoucher.source_type == source_type,
                GlVoucher.source_id == int(source_id),
                GlVoucher.status != "void",
            )
            .first()
        )
        if exists:
            return exists  # 幂等
    row = GlVoucher(
        voucher_no=next_doc_number(db, "gl_voucher"),
        period=period,
        status="draft",
        source_type=source_type,
        source_id=int(source_id) if source_id is not None else None,
        source_no=(data.get("source_no") or "").strip(),
        summary=(data.get("summary") or "").strip(),
        created_by=user,
    )
    db.add(row)
    db.flush()
    for acc, debit, credit, summary, i in resolved:
        db.add(
            GlVoucherLine(
                voucher_id=row.id,
                sort_order=i,
                account_code=acc.code,
                account_name=acc.name,
                debit=debit,
                credit=credit,
                summary=summary or row.summary,
            )
        )
    db.flush()
    return row


def review_voucher(db: Session, vid: int, *, user: str) -> GlVoucher:
    row, lines = get_voucher(db, vid)
    if row.status != "draft":
        raise ValueError(f"凭证状态 {row.status} 不可审核")
    if not lines:
        raise ValueError("无分录")
    row.status = "reviewed"
    row.reviewed_by = user
    row.reviewed_at = _now()
    db.flush()
    return row


def post_voucher(db: Session, vid: int, *, user: str) -> GlVoucher:
    row, lines = get_voucher(db, vid)
    if row.status != "reviewed":
        raise ValueError(f"凭证状态 {row.status} 不可过账（须已审核）")
    p = db.query(GlPeriod).filter(GlPeriod.period == row.period).first()
    if p and p.status == "closed":
        raise ValueError("期间已关账")
    for ln in lines:
        acc = db.query(GlAccount).filter(GlAccount.code == ln.account_code).first()
        if not acc:
            raise ValueError(f"科目 {ln.account_code} 不存在")
        # 余额按 debit 方向：借增贷减；credit 方向相反
        delta = float(ln.debit or 0) - float(ln.credit or 0)
        if acc.balance_dir == "credit":
            delta = -delta
        acc.balance = round(float(acc.balance or 0) + delta, 4)
    row.status = "posted"
    row.posted_by = user
    row.posted_at = _now()
    db.flush()
    return row


def try_auto_voucher(
    db: Session,
    *,
    source_type: str,
    source_id: int,
    source_no: str,
    amount: float,
    summary: str,
    lines: list[dict],
    user: str = "system",
) -> Optional[GlVoucher]:
    """业务钩子：失败不抛到主流程（调用方应用 try）。"""
    if amount <= 0:
        return None
    ensure_gl_seed(db, opening=False)
    return create_voucher(
        db,
        {
            "source_type": source_type,
            "source_id": source_id,
            "source_no": source_no,
            "summary": summary,
            "lines": lines,
        },
        user=user,
    )


# —— 业务模板 ——


def voucher_from_purchase_receipt(db: Session, *, receipt_id: int, receipt_no: str, amount: float, user: str) -> Optional[GlVoucher]:
    # 借原材料 / 贷应付账款
    return try_auto_voucher(
        db,
        source_type="purchase_receipt",
        source_id=receipt_id,
        source_no=receipt_no,
        amount=amount,
        summary=f"采购入库 {receipt_no}",
        lines=[
            {"account_code": "1403", "debit": amount, "credit": 0, "summary": "原材料入库"},
            {"account_code": "2202", "debit": 0, "credit": amount, "summary": "应付账款"},
        ],
        user=user,
    )


def voucher_from_outsource_receipt(db: Session, *, receipt_id: int, receipt_no: str, amount: float, user: str) -> Optional[GlVoucher]:
    return try_auto_voucher(
        db,
        source_type="outsource_receipt",
        source_id=receipt_id,
        source_no=receipt_no,
        amount=amount,
        summary=f"委托入库 {receipt_no}",
        lines=[
            {"account_code": "1405", "debit": amount, "credit": 0, "summary": "库存商品"},
            {"account_code": "2202", "debit": 0, "credit": amount, "summary": "应付账款"},
        ],
        user=user,
    )


def voucher_from_delivery(db: Session, *, delivery_id: int, delivery_no: str, amount: float, user: str) -> Optional[GlVoucher]:
    # 借应收账款 / 贷主营业务收入（简化，不同时结转成本）
    return try_auto_voucher(
        db,
        source_type="delivery_note",
        source_id=delivery_id,
        source_no=delivery_no,
        amount=amount,
        summary=f"发货确认 {delivery_no}",
        lines=[
            {"account_code": "1122", "debit": amount, "credit": 0, "summary": "应收账款"},
            {"account_code": "6001", "debit": 0, "credit": amount, "summary": "主营业务收入"},
        ],
        user=user,
    )


def voucher_from_payment(db: Session, *, payment_id: int, payment_no: str, amount: float, user: str) -> Optional[GlVoucher]:
    return try_auto_voucher(
        db,
        source_type="payment",
        source_id=payment_id,
        source_no=payment_no,
        amount=amount,
        summary=f"付款 {payment_no}",
        lines=[
            {"account_code": "2202", "debit": amount, "credit": 0, "summary": "核销应付"},
            {"account_code": "1002", "debit": 0, "credit": amount, "summary": "银行存款"},
        ],
        user=user,
    )


def voucher_from_receipt(db: Session, *, receipt_id: int, receipt_no: str, amount: float, user: str) -> Optional[GlVoucher]:
    return try_auto_voucher(
        db,
        source_type="receipt",
        source_id=receipt_id,
        source_no=receipt_no,
        amount=amount,
        summary=f"收款 {receipt_no}",
        lines=[
            {"account_code": "1002", "debit": amount, "credit": 0, "summary": "银行存款"},
            {"account_code": "1122", "debit": 0, "credit": amount, "summary": "核销应收"},
        ],
        user=user,
    )


def create_cost_accrual(db: Session, *, amount: float, user: str, remark: str = "") -> GlVoucher:
    """简版成本：借生产成本 / 贷原材料。"""
    if amount <= 0:
        raise ValueError("成本金额须大于 0")
    return create_voucher(
        db,
        {
            "source_type": "cost_accrual",
            "summary": remark or "生产耗用结转",
            "lines": [
                {"account_code": "5001", "debit": amount, "credit": 0, "summary": "生产成本"},
                {"account_code": "1403", "debit": 0, "credit": amount, "summary": "原材料耗用"},
            ],
        },
        user=user,
    )


def create_fixed_asset(db: Session, data: dict, *, user: str) -> FixedAsset:
    row = FixedAsset(
        asset_no=next_doc_number(db, "fixed_asset"),
        name=(data.get("name") or "").strip() or "固定资产",
        original_value=float(data.get("original_value") or 0),
        residual_rate=float(data.get("residual_rate") or 0.05),
        months=int(data.get("months") or 36),
        status="active",
        remark=(data.get("remark") or "").strip(),
        created_by=user,
    )
    if row.original_value <= 0:
        raise ValueError("原值须大于 0")
    db.add(row)
    db.flush()
    # 购置凭证：借固定资产 / 贷银行存款
    create_voucher(
        db,
        {
            "source_type": "fixed_asset",
            "source_id": row.id,
            "source_no": row.asset_no,
            "summary": f"购置固资 {row.asset_no}",
            "lines": [
                {"account_code": "1601", "debit": row.original_value, "credit": 0},
                {"account_code": "1002", "debit": 0, "credit": row.original_value},
            ],
        },
        user=user,
    )
    return row


def depreciate_asset(db: Session, asset_id: int, *, user: str) -> GlVoucher:
    row = db.query(FixedAsset).filter(FixedAsset.id == asset_id).first()
    if not row or row.status != "active":
        raise ValueError("固定资产不可折旧")
    depreciable = float(row.original_value or 0) * (1 - float(row.residual_rate or 0))
    monthly = round(depreciable / max(int(row.months or 1), 1), 4)
    remain = round(depreciable - float(row.accumulated_depr or 0), 4)
    amt = min(monthly, remain)
    if amt <= 0:
        raise ValueError("已提足折旧")
    row.accumulated_depr = round(float(row.accumulated_depr or 0) + amt, 4)
    v = create_voucher(
        db,
        {
            "source_type": "depreciation",
            "source_id": row.id,
            "source_no": row.asset_no,
            "summary": f"折旧 {row.asset_no}",
            "lines": [
                {"account_code": "6602", "debit": amt, "credit": 0, "summary": "管理费用-折旧"},
                {"account_code": "1602", "debit": 0, "credit": amt, "summary": "累计折旧"},
            ],
        },
        user=user,
    )
    db.flush()
    return v


def fx_adjustment(db: Session, *, user: str = "") -> dict:
    """无外币：跳过调汇。"""
    return {"skipped": True, "reason": "本期无外币科目，调汇跳过", "period": _period_str()}


def close_pnl(db: Session, *, user: str) -> GlVoucher:
    """损益结转：收入贷方余额 / 费用借方余额 → 本年利润。"""
    ensure_gl_seed(db, opening=False)
    period = get_open_period(db).period
    incomes = db.query(GlAccount).filter(GlAccount.category == "income", GlAccount.is_active.is_(True)).all()
    expenses = db.query(GlAccount).filter(GlAccount.category == "expense", GlAccount.is_active.is_(True)).all()
    lines = []
    income_total = 0.0
    expense_total = 0.0
    for acc in incomes:
        # 收入科目 credit 方向，余额为正表示贷方
        bal = float(acc.balance or 0)
        if bal > 1e-6:
            lines.append({"account_code": acc.code, "debit": bal, "credit": 0, "summary": f"结转 {acc.name}"})
            income_total += bal
    for acc in expenses:
        bal = float(acc.balance or 0)
        if bal > 1e-6:
            lines.append({"account_code": acc.code, "debit": 0, "credit": bal, "summary": f"结转 {acc.name}"})
            expense_total += bal
    net = round(income_total - expense_total, 4)
    if abs(income_total) < 1e-9 and abs(expense_total) < 1e-9:
        raise ValueError("本期无损益余额可结转")
    if net >= 0:
        lines.append({"account_code": "4103", "debit": 0, "credit": net, "summary": "结转本年利润"})
    else:
        lines.append({"account_code": "4103", "debit": abs(net), "credit": 0, "summary": "结转本年利润（亏损）"})
    v = create_voucher(
        db,
        {
            "period": period,
            "source_type": "pnl_close",
            "source_no": period,
            "summary": f"{period} 损益结转",
            "lines": lines,
        },
        user=user,
    )
    review_voucher(db, v.id, user=user)
    post_voucher(db, v.id, user=user)
    return v


def close_period(db: Session, *, user: str, period: str = "") -> GlPeriod:
    ensure_gl_seed(db, opening=False)
    period = (period or _period_str()).strip()
    p = db.query(GlPeriod).filter(GlPeriod.period == period).first()
    if not p:
        raise ValueError("期间不存在")
    if p.status == "closed":
        raise ValueError("期间已关账")
    drafts = (
        db.query(GlVoucher)
        .filter(GlVoucher.period == period, GlVoucher.status.in_(("draft", "reviewed")))
        .count()
    )
    if drafts:
        raise ValueError(f"仍有 {drafts} 张未过账凭证，不可关账")
    p.status = "closed"
    p.closed_at = _now()
    p.remark = (p.remark or "") + f"；关账人 {user}"
    db.flush()
    # 开启下一期间
    y, m = int(period[:4]), int(period[4:6])
    if m == 12:
        nxt = f"{y + 1}01"
    else:
        nxt = f"{y}{m + 1:02d}"
    if not db.query(GlPeriod).filter(GlPeriod.period == nxt).first():
        db.add(GlPeriod(period=nxt, status="open", opened_at=_now(), remark="自动开下期"))
        db.flush()
    return p


def period_to_dict(row: GlPeriod) -> dict:
    return {
        "id": row.id,
        "period": row.period,
        "status": row.status,
        "opened_at": row.opened_at,
        "closed_at": row.closed_at,
        "remark": row.remark or "",
    }


def list_periods(db: Session) -> list[GlPeriod]:
    ensure_gl_seed(db, opening=False)
    return db.query(GlPeriod).order_by(GlPeriod.period.desc()).all()


def asset_to_dict(row: FixedAsset) -> dict:
    return {
        "id": row.id,
        "asset_no": row.asset_no,
        "name": row.name,
        "original_value": row.original_value,
        "residual_rate": row.residual_rate,
        "months": row.months,
        "accumulated_depr": row.accumulated_depr,
        "status": row.status,
    }


def list_assets(db: Session) -> list[FixedAsset]:
    return db.query(FixedAsset).order_by(FixedAsset.id.desc()).all()
