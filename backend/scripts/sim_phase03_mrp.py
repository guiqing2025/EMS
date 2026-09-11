#!/usr/bin/env python3
"""阶段3验收模拟：需求→MRP展开→三类计划 + 库存预警 + HTTP。

用法（backend 目录，uvicorn 同库）:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase03_mrp.py
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
from models import (  # noqa: E402
    BomLine,
    BomModel,
    ErpSalesOrder,
    ErpStockProduct,
    WarehouseMaterial,
)
from planning_service import (  # noqa: E402
    generate_mrp,
    get_outsource_plan,
    get_production_plan,
    get_purchase_plan,
    preview_mrp,
    set_purchase_plan_status,
    stock_warnings,
)
from sales_service import (  # noqa: E402
    bind_sales_line_bom,
    create_sales_order,
    create_stock_order,
    get_sales_order,
    set_sales_order_status,
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
    print("=== 准备库 / 模拟 BOM+库存 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)

    bom = db.query(BomModel).filter(BomModel.model_code == "JL-MRP-FG", BomModel.purchase_no == "MRP-SIM").first()
    if not bom:
        bom = BomModel(
            internal_code="MRP1",
            customer_id="sim",
            customer_name="模拟客户A",
            model_code="JL-MRP-FG",
            purchase_no="MRP-SIM",
            model_name="MRP模拟成品",
            is_active=True,
            line_count=2,
            eng_review_status="approved",
        )
        db.add(bom)
        db.flush()
        db.add(
            BomLine(
                bom_model_id=bom.id,
                material_code="R-1001",
                material_name="电阻1001",
                qty_per=2,
                unit="PCS",
                process="SMT",
                sort_order=0,
                is_active=True,
            )
        )
        db.add(
            BomLine(
                bom_model_id=bom.id,
                material_code="OS-2001",
                material_name="委外插件件",
                qty_per=1,
                unit="PCS",
                process="委外加工",
                sort_order=1,
                is_active=True,
            )
        )
    else:
        # 确保有行
        n = db.query(BomLine).filter(BomLine.bom_model_id == bom.id).count()
        if n == 0:
            db.add(
                BomLine(
                    bom_model_id=bom.id,
                    material_code="R-1001",
                    material_name="电阻1001",
                    qty_per=2,
                    process="SMT",
                    is_active=True,
                )
            )
            db.add(
                BomLine(
                    bom_model_id=bom.id,
                    material_code="OS-2001",
                    material_name="委外插件件",
                    qty_per=1,
                    process="委外加工",
                    is_active=True,
                )
            )

    # 库存：R-1001 只有少量 → 缺口；OS-2001 无库存
    for code, name, qty in (("R-1001", "电阻1001", 10.0), ("OS-2001", "委外插件件", 0.0)):
        wm = (
            db.query(WarehouseMaterial)
            .filter(WarehouseMaterial.customer_id == "sim", WarehouseMaterial.material_code == code)
            .first()
        )
        if not wm:
            db.add(
                WarehouseMaterial(
                    customer_id="sim",
                    customer_name="模拟客户A",
                    material_code=code,
                    material_name=name,
                    qty=qty,
                    locked_qty=0,
                )
            )
        else:
            wm.qty = qty

    sp = db.query(ErpStockProduct).filter(ErpStockProduct.material_code == "JL-MRP-FG").first()
    if not sp:
        db.add(
            ErpStockProduct(
                material_code="JL-MRP-FG",
                material_name="MRP模拟成品",
                can_stock=True,
                safety_qty=100,
                is_active=True,
            )
        )
    else:
        sp.safety_qty = 100
        sp.is_active = True

    db.commit()
    bom_id = int(bom.id)
    ok(f"BOM#{bom_id} + 库存种子")

    print("\n=== 建确认销售单（绑 BOM）===")
    try:
        so = create_sales_order(
            db,
            {
                "customer_name": "模拟客户A",
                "require_bom": False,
                "remark": "阶段3 MRP",
                "lines": [
                    {
                        "material_code": "JL-MRP-FG",
                        "material_name": "MRP模拟成品",
                        "qty": 50,
                        "unit_price": 10,
                        "due_date": "2026-10-15",
                    }
                ],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so.id, "confirmed", user="WGQ")
        db.commit()
        so, lines = get_sales_order(db, so.id)
        bind_sales_line_bom(db, so.id, lines[0].id, bom_id)
        db.commit()
        so_id = so.id
        ok(f"销售单 {so.so_no} confirmed + BOM")
    except Exception as e:
        fail("建销售单", e)
        traceback.print_exc()
        return 1

    print("\n=== 备货单 confirmed ===")
    try:
        st = create_stock_order(
            db,
            {
                "stock_kind": "internal",
                "lines": [{"material_code": "JL-MRP-FG", "material_name": "MRP模拟成品", "qty": 20, "bom_model_id": bom_id}],
            },
            user="WGQ",
        )
        # create doesn't accept bom on line via create_stock_order - check if bom_model_id in replace
        set_stock_order_status(db, st.id, "confirmed", user="WGQ")
        db.commit()
        stock_id = st.id
        ok(f"备货单 {st.stock_no} confirmed")
    except Exception as e:
        fail("备货单", e)
        traceback.print_exc()
        db.rollback()
        stock_id = None

    print("\n=== MRP 预览 / 生成 ===")
    try:
        prev = preview_mrp(db, so_ids=[so_id], stock_ids=[stock_id] if stock_id else None, include_forecasts=False)
        assert prev["demand_count"] >= 1
        assert len(prev["production_lines"]) >= 1
        # 50*2=100 需电阻，库存10 → 缺口90；委外 50
        pur_codes = {p["material_code"]: p["qty"] for p in prev["purchase_lines"]}
        outs_codes = {p["material_code"]: p["qty"] for p in prev["outsource_lines"]}
        assert "R-1001" in pur_codes and pur_codes["R-1001"] > 0, pur_codes
        assert "OS-2001" in outs_codes and outs_codes["OS-2001"] > 0, outs_codes
        ok(
            f"预览 demand={prev['demand_count']} 采购={len(prev['purchase_lines'])} "
            f"生产={len(prev['production_lines'])} 委外={len(prev['outsource_lines'])}"
        )

        result = generate_mrp(
            db,
            so_ids=[so_id],
            stock_ids=[stock_id] if stock_id else None,
            include_forecasts=False,
            advance_status=True,
            user="WGQ",
        )
        db.commit()
        run = result["run"]
        pur_id = result["purchase_plan"]["id"]
        prod_id = result["production_plan"]["id"]
        outs_id = result["outsource_plan"]["id"]
        _, plines = get_purchase_plan(db, pur_id)
        _, dlines = get_production_plan(db, prod_id)
        _, olines = get_outsource_plan(db, outs_id)
        assert plines and dlines
        so2 = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_id).first()
        assert so2.status == "planning", so2.status
        ok(
            f"生成 {run['run_no']} → {result['purchase_plan']['plan_no']}/"
            f"{result['production_plan']['plan_no']}/{result['outsource_plan']['plan_no']} "
            f"SO→{so2.status} 委外行={len(olines)}"
        )

        set_purchase_plan_status(db, pur_id, "confirmed")
        db.commit()
        ok("采购计划确认")
    except Exception as e:
        fail("MRP", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 负向：无需求 ===")
    try:
        # 用不存在的 so_id
        try:
            preview_mrp(db, so_ids=[99999999], include_forecasts=False)
            fail("无需求应报错")
        except ValueError as ve:
            ok(f"负向：{ve}")
    except Exception as e:
        fail("负向测试", e)

    print("\n=== 库存预警 ===")
    try:
        warns = stock_warnings(db)
        codes = {w["material_code"] for w in warns}
        assert "JL-MRP-FG" in codes, warns
        ok(f"预警 {len(warns)} 条含 JL-MRP-FG")
    except Exception as e:
        fail("库存预警", e)

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
                with urllib.request.urlopen(r, timeout=30) as resp:
                    return json.loads(resp.read().decode() or "null")
            except urllib.error.HTTPError as he:
                raise RuntimeError(f"{method} {path} -> {he.code} {he.read().decode()}") from he

        ok("登录成功")
        # 再建一张 confirmed SO 供 HTTP 生成
        soh = api(
            "POST",
            "/api/sales/sales-orders",
            {
                "customer_name": "HTTP计划客户",
                "lines": [{"material_code": "JL-MRP-FG", "material_name": "MRP模拟成品", "qty": 5, "unit_price": 1}],
            },
        )
        api("POST", f"/api/sales/sales-orders/{soh['id']}/status", {"status": "confirmed"})
        lid = soh["lines"][0]["id"]
        api("POST", f"/api/sales/sales-orders/{soh['id']}/lines/{lid}/bind-bom", {"bom_model_id": bom_id})
        gen = api("POST", "/api/planning/mrp/generate", {"so_ids": [soh["id"]], "advance_status": True})
        ok(f"HTTP MRP {gen['run']['run_no']} 采购={gen['purchase_plan']['plan_no']}")
        plans = api("GET", "/api/planning/purchase-plans")
        ok(f"HTTP 采购计划列表={len(plans.get('items') or [])}")
        w = api("GET", "/api/planning/stock-warnings")
        ok(f"HTTP 预警={len(w.get('items') or [])}")
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
