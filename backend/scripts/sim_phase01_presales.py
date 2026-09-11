#!/usr/bin/env python3
"""阶段验收模拟：主数据(0) + 售前闭环(1)。无真实客户数据时用本脚本自测。

用法（在 backend 目录）:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase01_presales.py
"""
from __future__ import annotations

import json
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import Base, SessionLocal, engine  # noqa: E402
import models  # noqa: E402,F401
from migrate import migrate  # noqa: E402
from doc_number import list_doc_number_rules, next_doc_number  # noqa: E402
from master_data_service import ensure_master_defaults  # noqa: E402
from models import (  # noqa: E402
    ErpCustomer,
    ErpPriceItem,
    ErpStockProduct,
    ErpSupplier,
    ErpWarehouse,
    ErpSalesOrderLine,
)
from presales_service import (  # noqa: E402
    create_design_from_quote,
    create_inquiry,
    create_loan,
    create_mail,
    create_quote_from_inquiry,
    create_sample_order_from_quote,
    create_sales_order_from_quote,
    get_inquiry,
    update_inquiry,
    update_loan,
)
from quotation_service import set_status  # noqa: E402
from user_service import ensure_default_users, get_user_by_username  # noqa: E402

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


def main() -> int:
    print("=== 准备库 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)
    ensure_master_defaults(db)
    db.commit()

    print("\n=== 阶段0：主数据 ===")
    try:
        codes = {w.code for w in db.query(ErpWarehouse).filter(ErpWarehouse.is_active.is_(True)).all()}
        assert {"GOOD", "INSPECT", "RETURN", "WIP"} <= codes, codes
        ok(f"仓库维度齐全 {sorted(codes)}")
    except Exception as e:
        fail("仓库维度", e)

    try:
        rules = list_doc_number_rules(db)
        no = next_doc_number(db, "sales_order")
        db.commit()
        assert len(rules) >= 20 and no.startswith("SO")
        ok(f"单据编号 {len(rules)} 条，试号 {no}")
    except Exception as e:
        fail("单据编号", e)
        db.rollback()

    try:
        c = db.query(ErpCustomer).filter(ErpCustomer.code == "C-SIM-001").first()
        if not c:
            c = ErpCustomer(code="C-SIM-001", name="模拟客户A", contact="张工", phone="13800000000", is_active=True)
            db.add(c)
            db.flush()
        else:
            c.name = "模拟客户A"
            c.is_active = True
        s = db.query(ErpSupplier).filter(ErpSupplier.code == "S-SIM-001").first()
        if not s:
            s = ErpSupplier(code="S-SIM-001", name="模拟供应商B", is_active=True)
            db.add(s)
            db.flush()
        sp = db.query(ErpStockProduct).filter(ErpStockProduct.material_code == "JL-PCBA-001").first()
        if not sp:
            sp = ErpStockProduct(
                material_code="JL-PCBA-001",
                material_name="模拟成品板",
                unit="PCS",
                can_stock=True,
                safety_qty=50,
                is_active=True,
            )
            db.add(sp)
            db.flush()
        pr = (
            db.query(ErpPriceItem)
            .filter(ErpPriceItem.material_code == "JL-PCBA-001", ErpPriceItem.price_type == "standard")
            .first()
        )
        if not pr:
            pr = ErpPriceItem(
                price_type="standard",
                material_code="JL-PCBA-001",
                material_name="模拟成品板",
                unit_price=12.5,
                is_active=True,
            )
            db.add(pr)
            db.flush()
        db.commit()
        ok(f"客户={c.code} 供应商={s.code} 产品={sp.material_code} 价={pr.unit_price}")
    except Exception as e:
        fail("主数据 CRUD", e)
        db.rollback()
        return 1

    try:
        assert get_user_by_username(db, "WGQ")
        for name in ("sales", "purchasing", "production", "quality", "finance"):
            assert get_user_by_username(db, name), name
        ok("泳道角色种子账号存在")
    except Exception as e:
        fail("角色种子", e)

    print("\n=== 阶段1：售前闭环 ===")
    try:
        inq = create_inquiry(
            db,
            {
                "customer_id": c.id,
                "customer_name": c.name,
                "title": "模拟询价-PCBA",
                "contact": "李业务",
                "lines": [
                    {"material_code": "JL-PCBA-001", "material_name": "模拟成品板", "qty": 100, "unit": "PCS"},
                    {"material_code": "JL-PCBA-002", "material_name": "备选板", "qty": 20, "unit": "PCS"},
                ],
            },
            user="WGQ",
        )
        db.flush()
        row, lines = get_inquiry(db, inq.id)
        assert len(lines) == 2
        ok(f"询价单 {row.inquiry_no} 行数={len(lines)}")
    except Exception as e:
        fail("创建询价单", e)
        traceback.print_exc()
        return 1

    try:
        update_inquiry(db, inq.id, {"status": "submitted"}, user="WGQ")
        db.flush()
        quote = create_quote_from_inquiry(db, inq.id, user="WGQ")
        db.flush()
        assert quote.inquiry_id == inq.id
        ok(f"询价转报价 {quote.quote_no}")
    except Exception as e:
        fail("询价转报价", e)
        traceback.print_exc()
        return 1

    try:
        quote.supplier_name = "模拟供应商B"
        quote.supplier_cost = 8.0
        quote.sell_price = 15.5
        quote.quote_kind = "customer"
        quote.batch_qty = 100
        quote.unit_price = 15.5
        quote.grand_total = 1550
        set_status(db, quote.id, "calculated", username="WGQ")
        set_status(db, quote.id, "confirmed", username="WGQ")
        db.flush()
        assert quote.status == "confirmed"
        ok(f"报价确认 sell={quote.sell_price}")
    except Exception as e:
        fail("报价确认", e)
        traceback.print_exc()
        return 1

    try:
        design = create_design_from_quote(db, quote.id, user="WGQ")
        db.flush()
        ok(f"转设计 {design.design_no}")
    except Exception as e:
        fail("转设计", e)
        db.rollback()

    try:
        sample = create_sample_order_from_quote(db, quote.id, user="WGQ")
        db.flush()
        assert sample.qty == 100
        ok(f"转打样订单 {sample.sample_no}")
    except Exception as e:
        fail("转打样订单", e)
        db.rollback()

    try:
        so = create_sales_order_from_quote(db, quote.id, user="WGQ")
        db.flush()
        solines = db.query(ErpSalesOrderLine).filter(ErpSalesOrderLine.so_id == so.id).all()
        assert len(solines) == 1 and abs(solines[0].amount - 1550) < 0.01
        inq3, _ = get_inquiry(db, inq.id)
        assert inq3.status == "quoted", inq3.status
        ok(f"转销售订单 {so.so_no} 金额={solines[0].amount} 询价={inq3.status}")
    except Exception as e:
        fail("转销售订单", e)
        traceback.print_exc()
        db.rollback()

    try:
        mail = create_mail(
            db,
            {
                "inquiry_id": inq.id,
                "customer_name": c.name,
                "product_name": "模拟成品板样品",
                "channel": "mail",
                "tracking_no": "SF1234567890",
                "status": "sent",
                "sent_at": "2026-09-09",
            },
            user="WGQ",
        )
        loan = create_loan(
            db,
            {
                "customer_id": c.id,
                "customer_name": c.name,
                "product_code": "JL-PCBA-001",
                "product_name": "模拟成品板",
                "qty": 2,
                "status": "draft",
            },
            user="WGQ",
        )
        db.flush()
        update_loan(db, loan.id, {"status": "lent"}, user="WGQ")
        db.flush()
        assert loan.status == "lent" and loan.lent_at
        ok(f"样品邮寄 {mail.mail_no} / 借样 {loan.loan_no}")
    except Exception as e:
        fail("样品邮寄/借样", e)
        db.rollback()

    db.commit()

    # 负向：独立事务，避免 rollback 冲掉前面成功数据
    try:
        bad = create_inquiry(
            db,
            {"customer_name": "X", "title": "负向", "lines": [{"material_code": "X", "material_name": "X", "qty": 1}]},
            user="WGQ",
        )
        db.flush()
        bq = create_quote_from_inquiry(db, bad.id, user="WGQ")
        db.flush()
        try:
            create_sales_order_from_quote(db, bq.id, user="WGQ")
            fail("未确认报价应禁止转销售")
            db.rollback()
        except ValueError as ve:
            ok(f"负向拦截：{ve}")
            db.rollback()
    except Exception as e:
        fail("负向测试", e)
        db.rollback()

    print("\n=== HTTP API 冒烟 ===")
    try:
        req = urllib.request.Request(
            f"{API}/api/auth/login",
            data=json.dumps({"username": "WGQ", "password": "jb140313!"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            login = json.loads(resp.read().decode())
        token = login.get("token") or login.get("access_token") or ""
        if not token and isinstance(login.get("user"), dict):
            # 有的实现把 token 放顶层以外
            pass
        # 兼容多种返回
        for k in ("token", "access_token", "auth_token"):
            if login.get(k):
                token = login[k]
                break
        if not token:
            raise RuntimeError(f"login 无 token: {login}")

        def api(method: str, path: str, body=None):
            data = None if body is None else json.dumps(body).encode()
            r = urllib.request.Request(
                f"{API}{path}",
                data=data,
                headers={"Content-Type": "application/json", "X-Auth-Token": token},
                method=method,
            )
            try:
                with urllib.request.urlopen(r, timeout=15) as resp:
                    raw = resp.read().decode() or "null"
                    return json.loads(raw)
            except urllib.error.HTTPError as he:
                detail = he.read().decode()
                raise RuntimeError(f"{method} {path} -> {he.code} {detail}") from he

        ok(f"登录成功")
        boot = api("GET", "/api/master/bootstrap")
        ok(f"bootstrap ok={boot.get('ok')}")
        custs = api("GET", "/api/master/customers")
        ok(f"customers total={custs.get('total')}")
        inqs = api("GET", "/api/presales/inquiries")
        ok(f"inquiries={len(inqs.get('items') or [])}")
        sos = api("GET", "/api/presales/sales-orders")
        ok(f"sales-orders={len(sos.get('items') or [])}")
        created = api(
            "POST",
            "/api/presales/inquiries",
            {
                "customer_name": "API模拟客户",
                "title": "HTTP询价",
                "lines": [{"material_code": "API-1", "material_name": "API料", "qty": 5, "unit": "PCS"}],
            },
        )
        ok(f"HTTP 建询价 {created.get('inquiry_no')}")
        tq = api("POST", f"/api/presales/inquiries/{created['id']}/to-quote")
        ok(f"HTTP 转报价 {tq.get('quote_no')}")
        # 确认并转销售
        api("POST", f"/api/quotation/{tq['quote_id']}/status", {"status": "calculated"})
        api("POST", f"/api/quotation/{tq['quote_id']}/status", {"status": "confirmed"})
        so2 = api("POST", f"/api/presales/quotes/{tq['quote_id']}/to-sales-order")
        ok(f"HTTP 转销售 {so2.get('so_no')}")
    except Exception as e:
        fail("HTTP API", e)
        traceback.print_exc()

    db.close()
    print("\n========== 汇总 ==========")
    print(f"通过 {len(oks)} / 失败 {len(fails)}")
    for e in fails:
        print(" FAIL:", e)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
