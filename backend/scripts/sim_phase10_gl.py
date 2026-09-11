#!/usr/bin/env python3
"""阶段10验收：开账→业务自动凭证→审核过账→成本/折旧→损益结转→关账。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase10_gl.py
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
from gl_service import (  # noqa: E402
    close_period,
    close_pnl,
    create_cost_accrual,
    create_fixed_asset,
    depreciate_asset,
    ensure_gl_seed,
    fx_adjustment,
    get_voucher,
    list_vouchers,
    post_voucher,
    review_voucher,
)
from models import GlAccount, GlPeriod, GlVoucher, WarehouseMaterial  # noqa: E402
from purchase_service import (  # noqa: E402
    create_inspect_from_po,
    create_purchase_order,
    create_receipt_from_inspect,
    get_inspect,
    get_purchase_order,
    judge_inspect,
    post_receipt as post_po_receipt,
    register_arrival_barcode,
    set_purchase_order_status,
)
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


def post_all_drafts(db, user: str = "WGQ") -> int:
    n = 0
    for v in list_vouchers(db, status="draft", limit=500):
        review_voucher(db, v.id, user=user)
        post_voucher(db, v.id, user=user)
        n += 1
    for v in list_vouchers(db, status="reviewed", limit=500):
        post_voucher(db, v.id, user=user)
        n += 1
    return n


def main() -> int:
    print("=== 开账 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)
    boot = ensure_gl_seed(db, opening=True)
    db.commit()
    bank = db.query(GlAccount).filter(GlAccount.code == "1002").first()
    assert bank and float(bank.balance) >= 100000
    ok(f"期间 {boot['period']} 开账 银行存款={bank.balance}")

    print("\n=== 业务自动凭证 ===")
    try:
        po = create_purchase_order(
            db,
            {
                "supplier_name": "总账供应商",
                "lines": [{"material_code": "R-GL-001", "material_name": "原料", "qty": 5, "unit_price": 10}],
            },
            user="WGQ",
        )
        set_purchase_order_status(db, po.id, "confirmed", user="WGQ")
        _, lines = get_purchase_order(db, po.id)
        register_arrival_barcode(
            db, {"po_id": po.id, "po_line_id": lines[0].id, "barcode": f"G-{uuid.uuid4().hex[:8]}", "qty": 5}, user="WGQ"
        )
        insp = create_inspect_from_po(db, po.id, user="WGQ")
        db.flush()
        insp, ilines = get_inspect(db, insp.id)
        judge_inspect(db, insp.id, [{"line_id": ilines[0].id, "pass_qty": 5, "fail_qty": 0}], user="WGQ")
        rec = create_receipt_from_inspect(db, insp.id, user="WGQ")
        post_po_receipt(db, rec.id, user="WGQ")
        db.commit()
        v_po = db.query(GlVoucher).filter(GlVoucher.source_type == "purchase_receipt", GlVoucher.source_no == rec.receipt_no).first()
        assert v_po and v_po.status == "draft"
        ok(f"采购入库自动凭证 {v_po.voucher_no}")

        ensure_mat(db, "FG-GL-001", 50)
        db.commit()
        so = create_sales_order(
            db,
            {
                "customer_name": "总账客户",
                "lines": [{"material_code": "FG-GL-001", "material_name": "成品", "qty": 2, "unit_price": 100}],
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
        v_ar = db.query(GlVoucher).filter(GlVoucher.source_type == "delivery_note", GlVoucher.source_no == deli.delivery_no).first()
        assert v_ar
        ok(f"发货自动凭证 {v_ar.voucher_no}")

        n = post_all_drafts(db)
        db.commit()
        ok(f"审核过账 {n} 张凭证")
        income = db.query(GlAccount).filter(GlAccount.code == "6001").first()
        assert income and float(income.balance) >= 200
        ok(f"主营业务收入余额={income.balance}")
    except Exception as e:
        fail("业务凭证", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 成本 / 固资 / 调汇 ===")
    try:
        # 先保证原材料有账面，便于结转
        raw = db.query(GlAccount).filter(GlAccount.code == "1403").first()
        if raw and float(raw.balance or 0) < 50:
            # 手工补一笔已过账不方便；成本结转允许余额变负，金额用 20
            pass
        cv = create_cost_accrual(db, amount=20, user="WGQ", remark="演示耗用")
        review_voucher(db, cv.id, user="WGQ")
        post_voucher(db, cv.id, user="WGQ")
        db.commit()
        ok(f"成本结转 {cv.voucher_no}")

        asset = create_fixed_asset(db, {"name": "演示设备", "original_value": 3600, "months": 36}, user="WGQ")
        dv = depreciate_asset(db, asset.id, user="WGQ")
        post_all_drafts(db)
        db.commit()
        ok(f"固资 {asset.asset_no} 折旧 {dv.voucher_no}")

        fx = fx_adjustment(db, user="WGQ")
        assert fx.get("skipped") is True
        ok(f"调汇：{fx['reason']}")
    except Exception as e:
        fail("成本固资", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 损益结转 + 关账 ===")
    try:
        post_all_drafts(db)
        db.commit()
        pv = close_pnl(db, user="WGQ")
        db.commit()
        _, lines = get_voucher(db, pv.id)
        assert pv.status == "posted"
        ok(f"损益结转 {pv.voucher_no} 行数={len(lines)}")

        p = close_period(db, user="WGQ")
        db.commit()
        assert p.status == "closed"
        ok(f"期间 {p.period} 已关账")

        try:
            create_cost_accrual(db, amount=1, user="WGQ")
            # 若当前期间仍是已关账期间会失败；get_open_period 可能开了下期
            # 强制对已关账期间建凭证
            from gl_service import create_voucher

            create_voucher(
                db,
                {
                    "period": p.period,
                    "summary": "应失败",
                    "lines": [
                        {"account_code": "1001", "debit": 1, "credit": 0},
                        {"account_code": "1002", "debit": 0, "credit": 1},
                    ],
                },
                user="WGQ",
            )
            fail("关账后仍可记账")
            db.rollback()
        except ValueError as ve:
            ok(f"负向：关账后不可记账 — {ve}")
            db.rollback()
    except Exception as e:
        fail("月末", e)
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
        acc = api("GET", "/api/finance/gl/accounts")
        periods = api("GET", "/api/finance/gl/periods")
        vouchers = api("GET", "/api/finance/gl/vouchers")
        assert len(acc.get("items") or []) >= 10
        assert len(periods.get("items") or []) >= 1
        ok(f"HTTP 科目={len(acc['items'])} 期间={len(periods['items'])} 凭证={len(vouchers['items'])}")
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
