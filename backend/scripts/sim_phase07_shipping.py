#!/usr/bin/env python3
"""阶段7验收：销售订单→出库扣库→打包条码→发货→SO关闭+应收stub；库存不足拒绝。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase07_shipping.py
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
from models import ArReceivableStub, WarehouseMaterial  # noqa: E402
from sales_service import create_sales_order, get_sales_order, set_sales_order_status  # noqa: E402
from shipping_service import (  # noqa: E402
    confirm_delivery,
    create_delivery_from_issue,
    create_issue_from_so,
    delivery_print_payload,
    get_issue,
    post_issue,
    register_pack_barcode,
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


def stock_qty(db, code: str, owner: str = "internal") -> float:
    row = (
        db.query(WarehouseMaterial)
        .filter(WarehouseMaterial.customer_id == owner, WarehouseMaterial.material_code == code)
        .first()
    )
    return float(row.qty) if row else 0.0


def ensure_mat(db, code: str, qty: float, name: str = "") -> None:
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
                material_name=name or code,
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
    ensure_mat(db, "FG-SHIP-001", 200, "出货成品A")
    ensure_mat(db, "FG-SHIP-HTTP", 30, "HTTP出货成品")
    db.commit()
    ok("成品库存就绪")

    print("\n=== 合格全链路 ===")
    try:
        so = create_sales_order(
            db,
            {
                "customer_name": "模拟出货客户",
                "lines": [
                    {
                        "material_code": "FG-SHIP-001",
                        "material_name": "出货成品A",
                        "qty": 40,
                        "unit_price": 12.5,
                    }
                ],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so.id, "confirmed", user="WGQ")
        set_sales_order_status(db, so.id, "executing", user="WGQ")
        db.commit()
        ok(f"销售订单 {so.so_no} executing")

        before = stock_qty(db, "FG-SHIP-001")
        issue = create_issue_from_so(db, so.id, user="WGQ")
        post_issue(db, issue.id, user="WGQ")
        db.commit()
        after = stock_qty(db, "FG-SHIP-001")
        assert after == before - 40, (before, after)
        so2, lines = get_sales_order(db, so.id)
        assert float(lines[0].shipped_qty) == 40
        assert so2.status == "done"
        ok(f"出库过账 {issue.issue_no} 库存-40 SO→{so2.status} shipped={lines[0].shipped_qty}")

        bc = f"PACK-{uuid.uuid4().hex[:10]}"
        register_pack_barcode(
            db,
            {"issue_id": issue.id, "barcode": bc, "material_code": "FG-SHIP-001", "qty": 40, "box_no": "BOX-1"},
            user="WGQ",
        )
        db.commit()
        ok(f"打包条码 {bc}")

        deli = create_delivery_from_issue(db, issue.id, user="WGQ", carrier="顺丰", tracking_no="SF123")
        confirm_delivery(db, deli.id, user="WGQ")
        db.commit()
        ar = db.query(ArReceivableStub).filter(ArReceivableStub.source_no == deli.delivery_no).first()
        assert ar and ar.amount == 500.0  # 40*12.5
        issue2, _ = get_issue(db, issue.id)
        assert issue2.status == "delivered"
        payload = delivery_print_payload(db, deli.id)
        assert payload["delivery_no"] == deli.delivery_no
        assert any(p["barcode"] == bc for p in payload["pack_barcodes"])
        ok(f"发货确认 {deli.delivery_no} 应收={ar.amount} 打印含条码")
    except Exception as e:
        fail("合格链路", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 部分出货 ===")
    try:
        ensure_mat(db, "FG-SHIP-001", 100, "出货成品A")
        db.commit()
        so = create_sales_order(
            db,
            {
                "customer_name": "部分出货客户",
                "lines": [{"material_code": "FG-SHIP-001", "material_name": "出货成品A", "qty": 30, "unit_price": 1}],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so.id, "confirmed", user="WGQ")
        set_sales_order_status(db, so.id, "executing", user="WGQ")
        _, so_lines = get_sales_order(db, so.id)
        issue = create_issue_from_so(db, so.id, user="WGQ", line_qtys=[{"so_line_id": so_lines[0].id, "qty": 10}])
        post_issue(db, issue.id, user="WGQ")
        db.commit()
        so2, lines = get_sales_order(db, so.id)
        assert float(lines[0].shipped_qty) == 10
        assert so2.status == "partial_shipped"
        ok(f"部分出货 SO→{so2.status} shipped=10/30")
    except Exception as e:
        fail("部分出货", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 负向：库存不足 ===")
    try:
        ensure_mat(db, "FG-SHIP-001", 2, "出货成品A")
        db.commit()
        so = create_sales_order(
            db,
            {
                "customer_name": "库存不足客户",
                "lines": [{"material_code": "FG-SHIP-001", "material_name": "出货成品A", "qty": 10, "unit_price": 1}],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so.id, "confirmed", user="WGQ")
        set_sales_order_status(db, so.id, "executing", user="WGQ")
        issue = create_issue_from_so(db, so.id, user="WGQ")
        db.commit()
        try:
            post_issue(db, issue.id, user="WGQ")
            fail("库存不足应拒绝过账")
            db.rollback()
        except ValueError as ve:
            ok(f"负向拒绝过账：{ve}")
            db.rollback()
    except Exception as e:
        fail("负向", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== HTTP 冒烟 ===")
    try:
        ensure_mat(db, "FG-SHIP-HTTP", 30, "HTTP出货成品")
        db.commit()
        req = urllib.request.Request(
            f"{API}/api/auth/login",
            data=json.dumps({"username": "WGQ", "password": "jb140313!"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            login = json.loads(resp.read().decode())
        token = next((login[k] for k in ("token", "access_token", "auth_token") if login.get(k)), "")
        if not token:
            raise RuntimeError(login)

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
        so = api(
            "POST",
            "/api/sales/sales-orders",
            {
                "customer_name": "HTTP出货客户",
                "lines": [{"material_code": "FG-SHIP-HTTP", "material_name": "HTTP出货成品", "qty": 5, "unit_price": 8}],
            },
        )
        api("POST", f"/api/sales/sales-orders/{so['id']}/status", {"status": "confirmed"})
        api("POST", f"/api/sales/sales-orders/{so['id']}/status", {"status": "executing"})
        issue = api("POST", f"/api/shipping/issues/from-so/{so['id']}", {})
        api("POST", f"/api/shipping/issues/{issue['id']}/post")
        api(
            "POST",
            "/api/shipping/pack-barcodes",
            {"issue_id": issue["id"], "barcode": f"HP-{uuid.uuid4().hex[:8]}", "qty": 5, "box_no": "H1"},
        )
        deli = api("POST", f"/api/shipping/deliveries/from-issue/{issue['id']}", {"carrier": "京东"})
        api("POST", f"/api/shipping/deliveries/{deli['id']}/confirm")
        pr = api("GET", f"/api/shipping/deliveries/{deli['id']}/print")
        assert pr.get("delivery_no") == deli["delivery_no"]
        ok(f"HTTP 闭环 {so['so_no']} → {issue['issue_no']} → {deli['delivery_no']}")
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
