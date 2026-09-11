#!/usr/bin/env python3
"""阶段2验收模拟：销售/打样/备货生命周期 + BOM 闸门 + 旧 PO 导入。

用法（在 backend 目录，且 uvicorn 指向同一 EMS_DB）:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase02_sales.py
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
from models import BomModel, SrmOrder  # noqa: E402
from presales_service import create_sample_order  # noqa: E402
from sales_service import (  # noqa: E402
    bind_sales_line_bom,
    create_sales_order,
    create_sales_order_from_srm,
    create_stock_order,
    get_sales_order,
    get_stock_order,
    sample_to_sales_order,
    set_sales_order_status,
    set_sample_order_status,
    set_stock_order_status,
)
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


def main() -> int:
    print("=== 准备库 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)

    bom = db.query(BomModel).filter(BomModel.model_code == "JL-PCBA-001", BomModel.purchase_no == "SIM-SO").first()
    if not bom:
        bom = BomModel(
            internal_code="SIM01",
            customer_id="sim",
            customer_name="模拟客户A",
            model_code="JL-PCBA-001",
            purchase_no="SIM-SO",
            model_name="模拟成品板",
            is_active=True,
            line_count=0,
            eng_review_status="approved",
        )
        db.add(bom)
        db.flush()
    db.commit()
    bom_id = int(bom.id)
    print(f"  (sim bom_id={bom_id})")

    print("\n=== 2.1 销售订单生命周期 + BOM闸门 ===")
    try:
        so = create_sales_order(
            db,
            {
                "customer_name": "模拟客户A",
                "external_po_no": "PO-SIM-001",
                "require_bom": True,
                "remark": "阶段2模拟",
                "lines": [
                    {
                        "material_code": "JL-PCBA-001",
                        "material_name": "模拟成品板",
                        "qty": 50,
                        "unit_price": 15.5,
                        "due_date": "2026-10-01",
                    }
                ],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so.id, "confirmed", user="WGQ")
        db.commit()
        so_id = so.id
        ok(f"建单+确认 {so.so_no}")

        try:
            set_sales_order_status(db, so_id, "planning", user="WGQ")
            fail("未绑BOM应禁止planning")
            db.rollback()
        except ValueError as ve:
            ok(f"负向BOM闸门：{ve}")
            db.rollback()

        so, lines = get_sales_order(db, so_id)
        bind_sales_line_bom(db, so_id, lines[0].id, bom_id)
        set_sales_order_status(db, so_id, "planning", user="WGQ")
        set_sales_order_status(db, so_id, "executing", user="WGQ")
        db.commit()
        ok(f"绑BOM后 planning→executing")
    except Exception as e:
        fail("销售生命周期", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 2.2 打样订单 → 量产 ===")
    try:
        sample = create_sample_order(
            db,
            {
                "customer_name": "模拟客户A",
                "product_code": "JL-SAMPLE-001",
                "product_name": "打样板",
                "qty": 5,
                "unit_price": 20,
                "sample_attr": "new_product",
            },
            user="WGQ",
        )
        set_sample_order_status(db, sample.id, "confirmed", user="WGQ")
        set_sample_order_status(db, sample.id, "in_progress", user="WGQ")
        set_sample_order_status(db, sample.id, "done", user="WGQ")
        so2 = sample_to_sales_order(db, sample.id, user="WGQ")
        db.commit()
        assert so2.order_kind == "sample_convert"
        ok(f"打样 {sample.sample_no} → 销售 {so2.so_no}")
    except Exception as e:
        fail("打样转量产", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 2.3 备货单 ===")
    try:
        st = create_stock_order(
            db,
            {
                "stock_kind": "internal",
                "warehouse_code": "GOOD",
                "remark": "内部安全库存",
                "lines": [{"material_code": "JL-PCBA-001", "material_name": "模拟成品板", "qty": 200}],
            },
            user="WGQ",
        )
        set_stock_order_status(db, st.id, "confirmed", user="WGQ")
        set_stock_order_status(db, st.id, "planning", user="WGQ")
        db.commit()
        st2, slines = get_stock_order(db, st.id)
        assert st2.status == "planning" and len(slines) == 1
        ok(f"备货单 {st2.stock_no} → planning")
    except Exception as e:
        fail("备货单", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 2.5 旧 PO 导入 ===")
    try:
        srm = db.query(SrmOrder).filter(SrmOrder.line_key == "SIM-LINE-PHASE2").first()
        if not srm:
            srm = SrmOrder(
                line_key="SIM-LINE-PHASE2",
                purchase_no="SIM-PO-9001",
                purchase_seq="1",
                product_goods_no="JL-PCBA-001",
                product_goods_name="模拟成品板",
                batch_pur_qty=30,
                tax_amount=12,
                customer_name="模拟客户A",
                customer_id="sim",
                expect_arrival_date="2026-11-01",
                bom_model_id=bom_id,
            )
            db.add(srm)
            db.commit()
        # 若上次已导入，换新 line_key 后缀避免冲突
        existing = (
            db.query(models.ErpSalesOrder)
            .filter(models.ErpSalesOrder.source_srm_line_key == "SIM-LINE-PHASE2")
            .first()
        )
        if existing:
            ok(f"PO已导入过 {existing.so_no}（跳过重复建）")
            try:
                create_sales_order_from_srm(db, line_key="SIM-LINE-PHASE2", user="WGQ")
                fail("重复导入应被拒绝")
                db.rollback()
            except ValueError as ve:
                ok(f"重复导入拦截：{ve}")
                db.rollback()
        else:
            so3 = create_sales_order_from_srm(db, line_key="SIM-LINE-PHASE2", user="WGQ")
            db.commit()
            assert so3.order_kind == "srm_import" and so3.external_po_no == "SIM-PO-9001"
            ok(f"PO导入 {so3.so_no} external={so3.external_po_no}")
            try:
                create_sales_order_from_srm(db, line_key="SIM-LINE-PHASE2", user="WGQ")
                fail("重复导入应被拒绝")
                db.rollback()
            except ValueError as ve:
                ok(f"重复导入拦截：{ve}")
                db.rollback()
    except Exception as e:
        fail("旧PO导入", e)
        traceback.print_exc()
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
        token = ""
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

        ok("登录成功")
        created = api(
            "POST",
            "/api/sales/sales-orders",
            {
                "customer_name": "API客户",
                "require_bom": False,
                "lines": [{"material_code": "API-SO", "material_name": "API料", "qty": 3, "unit_price": 1}],
            },
        )
        ok(f"HTTP 建销售 {created.get('so_no')}")
        api("POST", f"/api/sales/sales-orders/{created['id']}/status", {"status": "confirmed"})
        api("POST", f"/api/sales/sales-orders/{created['id']}/status", {"status": "planning"})
        ok("HTTP 状态 → planning")
        st = api(
            "POST",
            "/api/sales/stock-orders",
            {
                "stock_kind": "internal",
                "lines": [{"material_code": "BH-1", "material_name": "备货料", "qty": 10}],
            },
        )
        ok(f"HTTP 建备货 {st.get('stock_no')}")
        sos = api("GET", "/api/sales/sales-orders")
        ok(f"HTTP 列表 sales={len(sos.get('items') or [])}")
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
