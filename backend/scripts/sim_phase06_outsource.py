#!/usr/bin/env python3
"""阶段6验收：委外单→发料→条码→送检→合格委托入库/不合格退货；不良不入 GOOD。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase06_outsource.py
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
from models import ApPayableStub, OutsourcePlan, OutsourcePlanLine, WarehouseMaterial  # noqa: E402
from outsource_service import (  # noqa: E402
    confirm_return,
    confirm_ship,
    create_inspect_from_ww,
    create_receipt_from_inspect,
    create_return_from_inspect,
    create_ship_from_ww,
    create_ww,
    create_ww_from_plan,
    get_inspect,
    get_ww,
    judge_inspect,
    post_receipt,
    register_barcode,
    set_ww_status,
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


def stock_qty(db, owner: str, code: str) -> float:
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
    ensure_mat(db, "WW-PART-001", 500, "委外半成品")
    ensure_mat(db, "WW-PART-BAD", 100, "委外不良半成品")
    ensure_mat(db, "WW-HTTP-1", 50, "HTTP委外料")
    db.commit()
    ok("内部库存就绪")

    print("\n=== 合格全链路（含发料扣库）===")
    try:
        before_ship = stock_qty(db, "internal", "WW-PART-001")
        ww = create_ww(
            db,
            {
                "supplier_name": "模拟委外厂A",
                "process": "镀金",
                "stock_owner": "internal",
                "lines": [
                    {
                        "material_code": "WW-PART-001",
                        "material_name": "委外半成品",
                        "qty": 50,
                        "unit_price": 2.0,
                        "process": "镀金",
                    },
                ],
            },
            user="WGQ",
        )
        set_ww_status(db, ww.id, "confirmed", user="WGQ")
        db.commit()
        ok(f"委外单 {ww.ww_no} confirmed")

        ship = create_ship_from_ww(db, ww.id, user="WGQ")
        confirm_ship(db, ship.id, user="WGQ")
        db.commit()
        after_ship = stock_qty(db, "internal", "WW-PART-001")
        assert after_ship == before_ship - 50, (before_ship, after_ship)
        ok(f"发料 {ship.ship_no} 扣库存 50 → {after_ship}")

        bc = f"WWBC-{uuid.uuid4().hex[:10]}"
        register_barcode(db, {"ww_id": ww.id, "barcode": bc, "material_code": "WW-PART-001", "qty": 50}, user="WGQ")
        db.commit()
        ok(f"条码 {bc}")

        insp = create_inspect_from_ww(db, ww.id, user="WGQ")
        db.flush()
        insp, ilines = get_inspect(db, insp.id)
        judge_inspect(db, insp.id, [{"line_id": ilines[0].id, "pass_qty": 50, "fail_qty": 0}], user="WGQ")
        db.commit()
        ok(f"送检判定 pass {insp.inspect_no}")

        before_in = stock_qty(db, "internal", "WW-PART-001")
        rec = create_receipt_from_inspect(db, insp.id, user="WGQ")
        post_receipt(db, rec.id, user="WGQ")
        db.commit()
        after_in = stock_qty(db, "internal", "WW-PART-001")
        assert after_in == before_in + 50, (before_in, after_in)
        ap = db.query(ApPayableStub).filter(ApPayableStub.source_no == rec.receipt_no).first()
        assert ap and ap.source_type == "outsource_receipt" and ap.amount == 100.0
        ww2, _ = get_ww(db, ww.id)
        assert ww2.status == "closed"
        ok(f"委托入库 {rec.receipt_no} 库存+50 应付={ap.amount} WW→{ww2.status}")
    except Exception as e:
        fail("合格链路", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 计划下推 ===")
    try:
        plan = OutsourcePlan(
            plan_no=f"WWJ-SIM-{uuid.uuid4().hex[:6]}",
            status="confirmed",
            remark="sim",
            created_by="WGQ",
        )
        db.add(plan)
        db.flush()
        db.add(
            OutsourcePlanLine(
                plan_id=plan.id,
                sort_order=0,
                material_code="WW-PART-001",
                material_name="委外半成品",
                qty=10,
                unit="PCS",
                process="镀金",
            )
        )
        db.flush()
        ww = create_ww_from_plan(db, plan.id, supplier_name="计划委外厂", user="WGQ")
        db.commit()
        assert ww.source_plan_no == plan.plan_no
        ok(f"计划下推 → {ww.ww_no} from {plan.plan_no}")
    except Exception as e:
        fail("计划下推", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 不合格退货（不入 GOOD）===")
    try:
        ensure_mat(db, "WW-PART-BAD", 100, "委外不良半成品")
        db.commit()
        ww = create_ww(
            db,
            {
                "supplier_name": "模拟委外厂B",
                "lines": [{"material_code": "WW-PART-BAD", "material_name": "不良半成品", "qty": 20, "unit_price": 1}],
            },
            user="WGQ",
        )
        set_ww_status(db, ww.id, "confirmed", user="WGQ")
        ship = create_ship_from_ww(db, ww.id, user="WGQ")
        confirm_ship(db, ship.id, user="WGQ")
        db.commit()

        insp = create_inspect_from_ww(db, ww.id, user="WGQ")
        db.flush()
        insp, ilines = get_inspect(db, insp.id)
        judge_inspect(db, insp.id, [{"line_id": ilines[0].id, "pass_qty": 0, "fail_qty": 20}], user="WGQ")
        db.commit()

        try:
            create_receipt_from_inspect(db, insp.id, user="WGQ")
            fail("全不合格应禁止生成委托入库")
            db.rollback()
        except ValueError as ve:
            ok(f"负向禁止入库：{ve}")
            db.rollback()

        before = stock_qty(db, "internal", "WW-PART-BAD")
        ret = create_return_from_inspect(db, insp.id, user="WGQ")
        confirm_return(db, ret.id, user="WGQ")
        db.commit()
        after = stock_qty(db, "internal", "WW-PART-BAD")
        assert after == before, (before, after)
        ww2, _ = get_ww(db, ww.id)
        assert ww2.status == "closed"
        ok(f"退货确认 {ret.return_no} 良品库存未变={after} WW→{ww2.status}")
    except Exception as e:
        fail("不合格链路", e)
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
        ww = api(
            "POST",
            "/api/outsource/orders",
            {
                "supplier_name": "HTTP委外厂",
                "process": "测试",
                "lines": [{"material_code": "WW-HTTP-1", "material_name": "HTTP料", "qty": 5, "unit_price": 3}],
            },
        )
        api("POST", f"/api/outsource/orders/{ww['id']}/status", {"status": "confirmed"})
        ship = api("POST", f"/api/outsource/ships/from-order/{ww['id']}")
        api("POST", f"/api/outsource/ships/{ship['id']}/confirm")
        api(
            "POST",
            "/api/outsource/barcodes",
            {"ww_id": ww["id"], "barcode": f"H-{uuid.uuid4().hex[:8]}", "qty": 5},
        )
        insp = api("POST", f"/api/outsource/inspects/from-order/{ww['id']}")
        api(
            "POST",
            f"/api/outsource/inspects/{insp['id']}/judge",
            {"lines": [{"line_id": insp["lines"][0]["id"], "pass_qty": 5, "fail_qty": 0}]},
        )
        rec = api("POST", f"/api/outsource/receipts/from-inspect/{insp['id']}")
        api("POST", f"/api/outsource/receipts/{rec['id']}/post")
        ok(f"HTTP 闭环 {ww['ww_no']} → {rec['receipt_no']}")
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
