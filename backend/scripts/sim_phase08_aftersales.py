#!/usr/bin/env python3
"""阶段8验收：投诉 / 销退补发·补货 / 借样转销售 / 盘点·调拨。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase08_aftersales.py
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
from aftersales_service import (  # noqa: E402
    branch_reissue,
    branch_replenish,
    confirm_return,
    convert_loan_to_so,
    create_complaint,
    create_return_from_issue,
    return_loan,
)
from models import ProductionOrder, WarehouseMaterial  # noqa: E402
from presales_service import create_loan, update_loan  # noqa: E402
from sales_service import create_sales_order, get_sales_order, set_sales_order_status  # noqa: E402
from shipping_service import (  # noqa: E402
    confirm_delivery,
    create_delivery_from_issue,
    create_issue_from_so,
    post_issue,
)
from user_service import ensure_default_users  # noqa: E402
from warehouse_aux_service import create_stocktake, create_transfer, post_stocktake, post_transfer  # noqa: E402

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


def stock(db, code: str, owner: str = "internal") -> float:
    row = (
        db.query(WarehouseMaterial)
        .filter(WarehouseMaterial.customer_id == owner, WarehouseMaterial.material_code == code)
        .first()
    )
    return float(row.qty) if row else 0.0


def ensure_mat(db, code: str, qty: float, owner: str = "internal", name: str = "") -> None:
    row = (
        db.query(WarehouseMaterial)
        .filter(WarehouseMaterial.customer_id == owner, WarehouseMaterial.material_code == code)
        .first()
    )
    if not row:
        db.add(
            WarehouseMaterial(
                customer_id=owner,
                customer_name="内部库存" if owner == "internal" else owner,
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
    ensure_mat(db, "FG-AS-001", 100, name="售后成品")
    ensure_mat(db, "FG-AS-002", 50, name="补货成品")
    ensure_mat(db, "JY-AS-001", 10, name="借样料")
    ensure_mat(db, "PD-AS-001", 20, name="盘点料")
    ensure_mat(db, "DB-AS-001", 30, name="调拨料")
    db.commit()
    ok("库存就绪")

    print("\n=== 销退 → 补发 ===")
    try:
        so = create_sales_order(
            db,
            {
                "customer_name": "售后客户A",
                "lines": [{"material_code": "FG-AS-001", "material_name": "售后成品", "qty": 20, "unit_price": 10}],
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
        before = stock(db, "FG-AS-001")
        ret = create_return_from_issue(db, issue.id, user="WGQ")
        confirm_return(db, ret.id, user="WGQ")
        db.commit()
        after = stock(db, "FG-AS-001")
        assert after == before + 20, (before, after)
        so2, lines = get_sales_order(db, so.id)
        assert float(lines[0].shipped_qty) == 0
        branch_reissue(db, ret.id, user="WGQ")
        db.commit()
        from aftersales_service import get_return

        ret, _ = get_return(db, ret.id)
        so3, lines3 = get_sales_order(db, so.id)
        assert float(lines3[0].shipped_qty) == 20
        assert ret.reissue_issue_id and ret.reissue_delivery_id
        ok(f"退货回库+补发 {ret.return_no} SO.shipped={lines3[0].shipped_qty}")
    except Exception as e:
        fail("补发分支", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 销退 → 补货生产 ===")
    try:
        ensure_mat(db, "FG-AS-002", 50)
        db.commit()
        so = create_sales_order(
            db,
            {
                "customer_name": "售后客户B",
                "lines": [{"material_code": "FG-AS-002", "material_name": "补货成品", "qty": 8, "unit_price": 5}],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so.id, "confirmed", user="WGQ")
        set_sales_order_status(db, so.id, "executing", user="WGQ")
        issue = create_issue_from_so(db, so.id, user="WGQ")
        post_issue(db, issue.id, user="WGQ")
        db.commit()
        ret = create_return_from_issue(db, issue.id, user="WGQ")
        confirm_return(db, ret.id, user="WGQ")
        branch_replenish(db, ret.id, user="WGQ")
        db.commit()
        from aftersales_service import get_return

        ret, _ = get_return(db, ret.id)
        mo = db.query(ProductionOrder).filter(ProductionOrder.id == ret.replenish_mo_id).first()
        assert mo and mo.qty == 8 and mo.source_so_id == so.id
        ok(f"补货 MO {mo.mo_no} qty={mo.qty}")
        so_for_complaint = so
    except Exception as e:
        fail("补货分支", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 投诉 + 借样转销售 ===")
    try:
        c = create_complaint(
            db,
            {"title": "外观不良", "customer_name": "售后客户A", "so_id": so_for_complaint.id, "content": "sim"},
            user="WGQ",
        )
        db.commit()
        ok(f"投诉单 {c.complaint_no} 关联 SO")

        loan = create_loan(
            db,
            {"customer_name": "借样客户", "product_code": "JY-AS-001", "product_name": "借样料", "qty": 2},
            user="WGQ",
        )
        update_loan(db, loan.id, {"status": "lent"}, user="WGQ")
        db.commit()
        so_loan = convert_loan_to_so(db, loan.id, user="WGQ", unit_price=99)
        db.commit()
        assert loan.status == "converted" and loan.converted_so_id == so_loan.id
        ok(f"借样转销售 {loan.loan_no} → {so_loan.so_no}")

        loan2 = create_loan(
            db,
            {"customer_name": "还入客户", "product_code": "JY-AS-001", "product_name": "借样料", "qty": 1},
            user="WGQ",
        )
        update_loan(db, loan2.id, {"status": "lent"}, user="WGQ")
        before = stock(db, "JY-AS-001")
        return_loan(db, loan2.id, user="WGQ", restock=True)
        db.commit()
        assert stock(db, "JY-AS-001") == before + 1
        ok(f"借样还入回库 {loan2.loan_no}")
    except Exception as e:
        fail("投诉/借样", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 盘点 + 调拨 ===")
    try:
        ensure_mat(db, "PD-AS-001", 20)
        db.commit()
        st = create_stocktake(
            db,
            {"stock_owner": "internal", "lines": [{"material_code": "PD-AS-001", "book_qty": 20, "count_qty": 18}]},
            user="WGQ",
        )
        post_stocktake(db, st.id, user="WGQ")
        db.commit()
        assert stock(db, "PD-AS-001") == 18
        ok(f"盘点过账 {st.stocktake_no} → 18")

        ensure_mat(db, "DB-AS-001", 30)
        ensure_mat(db, "DB-AS-001", 0, owner="cust-sim", name="调拨料")
        db.commit()
        tf = create_transfer(
            db,
            {
                "kind": "transfer",
                "from_owner": "internal",
                "to_owner": "cust-sim",
                "lines": [{"material_code": "DB-AS-001", "qty": 5}],
            },
            user="WGQ",
        )
        post_transfer(db, tf.id, user="WGQ")
        db.commit()
        assert stock(db, "DB-AS-001", "internal") == 25
        assert stock(db, "DB-AS-001", "cust-sim") == 5
        ok(f"调拨 {tf.doc_no} internal→cust-sim")
    except Exception as e:
        fail("盘点/调拨", e)
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
        c = api("POST", "/api/aftersales/complaints", {"title": f"HTTP投诉-{uuid.uuid4().hex[:6]}", "content": "x"})
        api("POST", f"/api/aftersales/complaints/{c['id']}/status", {"status": "closed"})
        st = api(
            "POST",
            "/api/warehouse-aux/stocktakes",
            {"lines": [{"material_code": "PD-AS-001", "book_qty": 18, "count_qty": 18}]},
        )
        api("POST", f"/api/warehouse-aux/stocktakes/{st['id']}/post")
        ok(f"HTTP 投诉 {c['complaint_no']} + 盘点 {st['stocktake_no']}")
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
