#!/usr/bin/env python3
"""流程链验收：全程只走 flow-chain / push，按流程图顺序推进。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase_flow_chain.py
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
from bom_erp_service import create_bom  # noqa: E402
from flow_chain_service import get_flow_chain, push_flow_step  # noqa: E402
from models import WarehouseMaterial  # noqa: E402
from sales_service import bind_sales_line_bom, create_sales_order, get_sales_order  # noqa: E402
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
        row.qty = max(float(row.qty or 0), qty)


def action_codes(chain: dict) -> list[str]:
    return [a["code"] for a in chain.get("next_actions") or []]


def main() -> int:
    print("=== 准备 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)
    tag = uuid.uuid4().hex[:6]
    fg = f"FG-FLOW-{tag}"
    bom = create_bom(
        db,
        {
            "model_code": fg,
            "model_name": "流程链成品",
            "customer_name": "流程链客户",
            "lines": [{"material_code": f"R-FLOW-{tag}", "material_name": "电阻", "qty_per": 1, "process": "SMT"}],
        },
        user="WGQ",
    )
    ensure_mat(db, fg, 100)
    ensure_mat(db, f"R-FLOW-{tag}", 50)
    so = create_sales_order(
        db,
        {
            "customer_name": f"流程链客户-{tag}",
            "lines": [{"material_code": fg, "material_name": "流程链成品", "qty": 10, "unit_price": 5}],
        },
        user="WGQ",
    )
    _, lines = get_sales_order(db, so.id)
    bind_sales_line_bom(db, so.id, lines[0].id, bom.id)
    db.commit()
    ok(f"SO {so.so_no} BOM={bom.id} FG库存就绪")

    print("\n=== 服务层 push 顺序 ===")
    try:
        chain = get_flow_chain(db, so.id)
        assert "confirm_so" in action_codes(chain)
        ok(f"草稿 next={action_codes(chain)}")

        r = push_flow_step(db, so.id, "confirm_so", user="WGQ")
        db.commit()
        chain = r["chain"]
        assert "mrp" in action_codes(chain)
        ok(f"确认后 next={action_codes(chain)}")

        r = push_flow_step(db, so.id, "mrp", user="WGQ")
        db.commit()
        chain = r["chain"]
        assert "confirm_plans" in action_codes(chain)
        ok(f"MRP后 next={action_codes(chain)} plans={len(chain['steps'][2]['docs'])}")

        r = push_flow_step(db, so.id, "confirm_plans", user="WGQ")
        db.commit()
        chain = r["chain"]
        codes = action_codes(chain)
        assert any(c.startswith("push_") for c in codes)
        ok(f"计划确认后 next={codes}")

        if "push_execute" in codes:
            r = push_flow_step(db, so.id, "push_execute", user="WGQ")
        else:
            for c in list(codes):
                if c.startswith("push_"):
                    r = push_flow_step(db, so.id, c, user="WGQ", plan_id=next(
                        (a.get("plan_id") for a in chain["next_actions"] if a["code"] == c), None
                    ))
                    chain = r["chain"]
        db.commit()
        chain = get_flow_chain(db, so.id)
        assert "issue_from_so" in action_codes(chain)
        ok(f"执行下推后 next={action_codes(chain)}")

        r = push_flow_step(db, so.id, "issue_from_so", user="WGQ")
        db.commit()
        chain = r["chain"]
        assert "post_issue" in action_codes(chain)
        ok(f"出库草稿 next={action_codes(chain)}")

        r = push_flow_step(db, so.id, "post_issue", user="WGQ", issue_id=chain["next_actions"][0].get("issue_id"))
        db.commit()
        chain = r["chain"]
        assert "delivery_from_issue" in action_codes(chain)
        ok(f"出库过账 next={action_codes(chain)}")

        r = push_flow_step(db, so.id, "delivery_from_issue", user="WGQ")
        db.commit()
        chain = r["chain"]
        assert "confirm_delivery" in action_codes(chain)
        ok(f"发货单 next={action_codes(chain)}")

        r = push_flow_step(db, so.id, "confirm_delivery", user="WGQ")
        db.commit()
        chain = r["chain"]
        ship = next(s for s in chain["steps"] if s["key"] == "shipping")
        ar = next(s for s in chain["steps"] if s["key"] == "finance_ar")
        assert ship["status"] == "done"
        assert ar["status"] in ("done", "active")
        ok(f"发货确认 shipping={ship['status']} ar={ar['status']} actions={action_codes(chain)}")
    except Exception as e:
        fail("服务层流程链", e)
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
                with urllib.request.urlopen(r, timeout=30) as resp:
                    return json.loads(resp.read().decode() or "null")
            except urllib.error.HTTPError as he:
                raise RuntimeError(f"{method} {path} -> {he.code} {he.read().decode()}") from he

        ok("登录成功")
        # 新开一张走 HTTP push
        so2 = api(
            "POST",
            "/api/sales/sales-orders",
            {
                "customer_name": f"HTTP流程-{tag}",
                "lines": [{"material_code": fg, "material_name": "流程链成品", "qty": 2, "unit_price": 1}],
            },
        )
        so2_id = so2["id"]
        lid = (so2.get("lines") or [{}])[0].get("id")
        if lid:
            api("POST", f"/api/sales/sales-orders/{so2_id}/lines/{lid}/bind-bom", {"bom_model_id": bom.id})
        chain = api("GET", f"/api/sales/sales-orders/{so2_id}/flow-chain")
        assert chain["so_id"] == so2_id
        ok(f"HTTP flow-chain {chain['so_no']}")
        for step in ("confirm_so", "mrp", "confirm_plans"):
            out = api("POST", f"/api/sales/sales-orders/{so2_id}/push/{step}", {})
            assert out.get("ok") is True or out.get("chain")
            ok(f"HTTP push {step}")
        chain = api("GET", f"/api/sales/sales-orders/{so2_id}/flow-chain")
        if any(a["code"] == "push_execute" for a in chain.get("next_actions") or []):
            api("POST", f"/api/sales/sales-orders/{so2_id}/push/push_execute", {})
            ok("HTTP push_execute")
        api("POST", f"/api/sales/sales-orders/{so2_id}/push/issue_from_so", {})
        api("POST", f"/api/sales/sales-orders/{so2_id}/push/post_issue", {})
        api("POST", f"/api/sales/sales-orders/{so2_id}/push/delivery_from_issue", {})
        api("POST", f"/api/sales/sales-orders/{so2_id}/push/confirm_delivery", {})
        chain = api("GET", f"/api/sales/sales-orders/{so2_id}/flow-chain")
        ship = next(s for s in chain["steps"] if s["key"] == "shipping")
        assert ship["status"] == "done"
        ok(f"HTTP 全链完成 shipping={ship['status']}")
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
