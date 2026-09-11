#!/usr/bin/env python3
"""阶段9验收：入库→应付→付款；发货→应收→收款；出纳账户流水对上。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase09_finance.py
"""
from __future__ import annotations

import json
import sys
import traceback
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Base, SessionLocal, engine  # noqa: E402
import models  # noqa: E402,F401
from migrate import migrate  # noqa: E402
from finance_service import (  # noqa: E402
    approve_payment_request,
    create_bill,
    create_invoice,
    create_other_expense,
    create_other_income,
    create_payment_from_request,
    create_payment_request,
    create_receipt,
    ensure_default_accounts,
    list_accounts,
    post_payment,
    post_receipt,
    transfer_accounts,
)
from models import ApPayableStub, ArReceivableStub, CashAccount, WarehouseMaterial  # noqa: E402
from purchase_service import create_purchase_order, create_receipt_from_inspect, create_inspect_from_po, get_inspect, judge_inspect, post_receipt as post_po_receipt, register_arrival_barcode, set_purchase_order_status, get_purchase_order  # noqa: E402
from sales_service import create_sales_order, set_sales_order_status  # noqa: E402
from shipping_service import confirm_delivery, create_delivery_from_issue, create_issue_from_so, post_issue  # noqa: E402
from user_service import ensure_default_users  # noqa: E402

API = "http://127.0.0.1:8001"
oks: list[str] = []
fails: list[str] = []


def ok(msg: str) -> None:
    oks.append(msg)
    print(f"  ✓ {msg}")


def fail(msg: str, exc: BaseException | None = None) -> None:
    text = f"{msg}: {exc}" if exc else msg
    fails.append(text)
    print(f"  ✗ {text}")


def ensure_mat(db, code: str, qty: float) -> None:
    row = (
        db.query(WarehouseMaterial)
        .filter(WarehouseMaterial.customer_id == "internal", WarehouseMaterial.material_code == code)
        .first()
    )
    if not row:
        db.add(
            WarehouseMaterial(
                customer_id="internal",
                customer_name="内部库存",
                material_code=code,
                material_name=code,
                qty=qty,
                locked_qty=0,
            )
        )
    else:
        row.qty = qty


def main() -> int:
    print("=== 准备 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)
    ensure_default_accounts(db)
    ensure_mat(db, "FG-FIN-001", 200)
    db.commit()
    bank = db.query(CashAccount).filter(CashAccount.code == "BANK-MAIN").first()
    cash = db.query(CashAccount).filter(CashAccount.code == "CASH").first()
    assert bank and cash
    bank.balance = 100000.0
    cash.balance = 0.0
    db.commit()
    ok(f"账户就绪 BANK={bank.balance} CASH={cash.balance}")

    print("\n=== 入库 → 应付 → 付款 ===")
    try:
        po = create_purchase_order(
            db,
            {
                "supplier_name": "财务供应商A",
                "lines": [{"material_code": "R-FIN-001", "material_name": "财务料", "qty": 10, "unit_price": 20}],
            },
            user="WGQ",
        )
        set_purchase_order_status(db, po.id, "confirmed", user="WGQ")
        _, lines = get_purchase_order(db, po.id)
        register_arrival_barcode(
            db, {"po_id": po.id, "po_line_id": lines[0].id, "barcode": f"F-{uuid.uuid4().hex[:8]}", "qty": 10}, user="WGQ"
        )
        insp = create_inspect_from_po(db, po.id, user="WGQ")
        db.flush()
        insp, ilines = get_inspect(db, insp.id)
        judge_inspect(db, insp.id, [{"line_id": ilines[0].id, "pass_qty": 10, "fail_qty": 0}], user="WGQ")
        rec = create_receipt_from_inspect(db, insp.id, user="WGQ")
        post_po_receipt(db, rec.id, user="WGQ")
        db.commit()
        ap = db.query(ApPayableStub).filter(ApPayableStub.source_no == rec.receipt_no).first()
        assert ap and float(ap.amount) == 200.0
        ok(f"应付 AP#{ap.id} amount=200 from {rec.receipt_no}")

        before = float(bank.balance)
        pr = create_payment_request(db, {"ap_ids": [ap.id]}, user="WGQ")
        approve_payment_request(db, pr.id, user="WGQ", approve=True)
        pay = create_payment_from_request(db, pr.id, account_id=bank.id, user="WGQ")
        post_payment(db, pay.id, user="WGQ")
        db.commit()
        db.refresh(bank)
        db.refresh(ap)
        assert ap.status == "cleared"
        assert float(bank.balance) == before - 200
        ok(f"付款 {pay.payment_no} AP cleared BANK→{bank.balance}")
    except Exception as e:
        fail("应付付款", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 发货 → 应收 → 收款 ===")
    try:
        ensure_mat(db, "FG-FIN-001", 200)
        db.commit()
        so = create_sales_order(
            db,
            {
                "customer_name": "财务客户A",
                "lines": [{"material_code": "FG-FIN-001", "material_name": "成品", "qty": 4, "unit_price": 50}],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so.id, "confirmed", user="WGQ")
        set_sales_order_status(db, so.id, "executing", user="WGQ")
        issue = create_issue_from_so(db, so.id, user="WGQ")
        post_issue(db, issue.id, user="WGQ")
        deli = create_delivery_from_issue(db, issue.id, user="WGQ")
        confirm_delivery(db, deli.id, user="WGQ")
        db.commit()
        ar = db.query(ArReceivableStub).filter(ArReceivableStub.source_no == deli.delivery_no).first()
        assert ar and float(ar.amount) == 200.0
        ok(f"应收 AR#{ar.id} amount=200 from {deli.delivery_no}")

        db.refresh(bank)
        before = float(bank.balance)
        rc = create_receipt(db, {"account_id": bank.id, "ar_ids": [ar.id]}, user="WGQ")
        post_receipt(db, rc.id, user="WGQ")
        db.commit()
        db.refresh(bank)
        db.refresh(ar)
        assert ar.status == "cleared"
        assert float(bank.balance) == before + 200
        ok(f"收款 {rc.receipt_no} AR cleared BANK→{bank.balance}")
    except Exception as e:
        fail("应收收款", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 其他费用 + 调拨 + 票据发票 ===")
    try:
        oe = create_other_expense(db, {"amount": 30, "supplier_name": "快递公司"}, user="WGQ")
        oi = create_other_income(db, {"amount": 15, "customer_name": "杂项客户"}, user="WGQ")
        db.commit()
        ok(f"其他费用 {oe.source_no}=30 / 收入 {oi.source_no}=15")

        db.refresh(bank)
        db.refresh(cash)
        b0, c0 = float(bank.balance), float(cash.balance)
        transfer_accounts(db, {"from_account_id": bank.id, "to_account_id": cash.id, "amount": 500}, user="WGQ")
        db.commit()
        db.refresh(bank)
        db.refresh(cash)
        assert float(bank.balance) == b0 - 500
        assert float(cash.balance) == c0 + 500
        ok(f"调拨 BANK→CASH 500 余额 {bank.balance}/{cash.balance}")

        inv = create_invoice(db, {"direction": "in", "counterparty": "财务供应商A", "amount": 200, "related_doc_no": "FK"}, user="WGQ")
        bill = create_bill(db, {"bill_kind": "payable", "counterparty": "财务供应商A", "amount": 100, "due_date": "2026-12-31"}, user="WGQ")
        db.commit()
        ok(f"发票 {inv.invoice_no} / 票据 {bill.bill_no}")
    except Exception as e:
        fail("其他/调拨/票", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== HTTP 冒烟 ===")
    try:
        req = urllib.request.Request(
            f"{API}/api/auth/login",
            data=json.dumps({"username": "WGQ", "password": "jb140313!"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            login = json.loads(resp.read().decode())
        token = next((login[k] for k in ("token", "access_token", "auth_token") if login.get(k)), "")

        def api(method: str, path: str, body=None):
            data = None if body is None else json.dumps(body).encode()
            r = urllib.request.Request(
                f"{API}{path}",
                data=data,
                headers={"Content-Type": "application/json", "X-Auth-Token": token},
                method=method,
            )
            try:
                with urllib.request.urlopen(r, timeout=20) as resp:
                    return json.loads(resp.read().decode() or "null")
            except urllib.error.HTTPError as he:
                raise RuntimeError(f"{method} {path} -> {he.code} {he.read().decode()}") from he

        ok("登录成功")
        ap = api("GET", "/api/finance/ap")
        ar = api("GET", "/api/finance/ar")
        acc = api("GET", "/api/finance/accounts")
        assert "items" in ap and "summary" in ap
        assert "items" in ar and "summary" in ar
        assert len(acc.get("items") or []) >= 2
        oe = api("POST", "/api/finance/ap/other-expense", {"amount": 1, "supplier_name": "HTTP费"})
        ok(f"HTTP AP items={len(ap['items'])} AR={len(ar['items'])} 其他费={oe['source_no']}")
    except Exception as e:
        fail("HTTP 冒烟", e)
        traceback.print_exc()

    db.close()
    print(f"\n=== 结果：通过 {len(oks)} / 失败 {len(fails)} ===")
    for f in fails:
        print(f"  FAIL: {f}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
