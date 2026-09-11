#!/usr/bin/env python3
"""阶段4验收：采购单→条码→送检→合格入库/不合格退货；不良不入 GOOD。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase04_purchase.py
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
from models import ApPayableStub, WarehouseMaterial  # noqa: E402
from purchase_service import (  # noqa: E402
    confirm_return,
    create_inspect_from_po,
    create_purchase_order,
    create_receipt_from_inspect,
    create_return_from_inspect,
    get_purchase_order,
    get_receipt,
    judge_inspect,
    post_receipt,
    register_arrival_barcode,
    set_purchase_order_status,
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


def main() -> int:
    print("=== 准备 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)
    db.commit()

    print("\n=== 合格全链路 ===")
    try:
        po = create_purchase_order(
            db,
            {
                "supplier_name": "模拟供应商B",
                "stock_owner": "internal",
                "lines": [
                    {"material_code": "R-PUR-001", "material_name": "采购电阻", "qty": 100, "unit_price": 0.5},
                ],
            },
            user="WGQ",
        )
        set_purchase_order_status(db, po.id, "confirmed", user="WGQ")
        db.commit()
        ok(f"采购单 {po.po_no} confirmed")

        bc = f"ARR-{uuid.uuid4().hex[:10]}"
        _, lines = get_purchase_order(db, po.id)
        register_arrival_barcode(
            db,
            {"po_id": po.id, "po_line_id": lines[0].id, "barcode": bc, "qty": 100},
            user="WGQ",
        )
        db.commit()
        ok(f"到货条码 {bc}")

        insp = create_inspect_from_po(db, po.id, user="WGQ")
        db.flush()
        from purchase_service import get_inspect

        insp, ilines = get_inspect(db, insp.id)
        judge_inspect(
            db,
            insp.id,
            [{"line_id": ilines[0].id, "pass_qty": 100, "fail_qty": 0}],
            user="WGQ",
        )
        db.commit()
        ok(f"送检判定 pass {insp.inspect_no}")

        before = stock_qty(db, "internal", "R-PUR-001")
        rec = create_receipt_from_inspect(db, insp.id, user="WGQ")
        post_receipt(db, rec.id, user="WGQ")
        db.commit()
        after = stock_qty(db, "internal", "R-PUR-001")
        assert after == before + 100, (before, after)
        ap = db.query(ApPayableStub).filter(ApPayableStub.source_no == rec.receipt_no).first()
        assert ap and ap.amount == 50.0
        po2, _ = get_purchase_order(db, po.id)
        assert po2.status == "closed"
        ok(f"入库过账 {rec.receipt_no} 库存+100 应付={ap.amount} PO→{po2.status}")
    except Exception as e:
        fail("合格链路", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 不合格退货（不入 GOOD）===")
    try:
        po = create_purchase_order(
            db,
            {
                "supplier_name": "模拟供应商B",
                "lines": [{"material_code": "R-PUR-002", "material_name": "不良料", "qty": 20, "unit_price": 1}],
            },
            user="WGQ",
        )
        set_purchase_order_status(db, po.id, "confirmed", user="WGQ")
        db.commit()
        _, lines = get_purchase_order(db, po.id)
        register_arrival_barcode(
            db,
            {"po_id": po.id, "po_line_id": lines[0].id, "barcode": f"BAD-{uuid.uuid4().hex[:8]}", "qty": 20},
            user="WGQ",
        )
        insp = create_inspect_from_po(db, po.id, user="WGQ")
        db.flush()
        from purchase_service import get_inspect

        insp, ilines = get_inspect(db, insp.id)
        judge_inspect(db, insp.id, [{"line_id": ilines[0].id, "pass_qty": 0, "fail_qty": 20}], user="WGQ")
        db.commit()

        try:
            create_receipt_from_inspect(db, insp.id, user="WGQ")
            fail("全不合格应禁止生成入库单")
            db.rollback()
        except ValueError as ve:
            ok(f"负向禁止入库：{ve}")
            db.rollback()

        before = stock_qty(db, "internal", "R-PUR-002")
        ret = create_return_from_inspect(db, insp.id, user="WGQ")
        confirm_return(db, ret.id, user="WGQ")
        db.commit()
        after = stock_qty(db, "internal", "R-PUR-002")
        assert after == before, (before, after)
        ok(f"退货确认 {ret.return_no} 良品库存未变={after}")
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
        po = api(
            "POST",
            "/api/purchase/orders",
            {
                "supplier_name": "HTTP供应商",
                "lines": [{"material_code": "R-HTTP-1", "material_name": "HTTP料", "qty": 10, "unit_price": 2}],
            },
        )
        api("POST", f"/api/purchase/orders/{po['id']}/status", {"status": "confirmed"})
        api(
            "POST",
            "/api/purchase/arrivals",
            {"po_id": po["id"], "po_line_id": po["lines"][0]["id"], "barcode": f"H-{uuid.uuid4().hex[:8]}", "qty": 10},
        )
        insp = api("POST", f"/api/purchase/inspects/from-po/{po['id']}")
        api(
            "POST",
            f"/api/purchase/inspects/{insp['id']}/judge",
            {"lines": [{"line_id": insp["lines"][0]["id"], "pass_qty": 8, "fail_qty": 2}]},
        )
        rec = api("POST", f"/api/purchase/receipts/from-inspect/{insp['id']}")
        api("POST", f"/api/purchase/receipts/{rec['id']}/post")
        ret = api("POST", f"/api/purchase/returns/from-inspect/{insp['id']}")
        api("POST", f"/api/purchase/returns/{ret['id']}/confirm")
        ok(f"HTTP 部分合格：入库 {rec['receipt_no']} + 退货 {ret['return_no']}")
        stubs = api("GET", "/api/purchase/ap-stubs")
        ok(f"HTTP 应付挂钩 {len(stubs.get('items') or [])} 条")
    except Exception as e:
        fail("HTTP", e)
        traceback.print_exc()

    db.close()
    print("\n========== 汇总 ==========")
    print(f"通过 {len(oks)} / 失败 {len(fails)}")
    for e in fails:
        print(" FAIL:", e)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
