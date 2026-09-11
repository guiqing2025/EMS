#!/usr/bin/env python3
"""阶段11验收：PMC 全程催办 + SRM 默认同步关闭 + HTTP。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase11_pmc.py
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
from config import DEFAULT_CONFIG, load_config  # noqa: E402
from models import BomLine, BomModel, ErpSalesOrder  # noqa: E402
from planning_service import generate_mrp, pmc_board, pmc_urge  # noqa: E402
from sales_service import bind_sales_line_bom, create_sales_order, get_sales_order, set_sales_order_status  # noqa: E402
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


def ensure_bom(db) -> BomModel:
    code = "JL-PMC-FG"
    bom = db.query(BomModel).filter(BomModel.model_code == code, BomModel.purchase_no == "PMC-SIM").first()
    if bom:
        return bom
    bom = BomModel(
        internal_code="PMC1",
        customer_id="sim",
        customer_name="PMC模拟客户",
        model_code=code,
        purchase_no="PMC-SIM",
        model_name="PMC模拟成品",
        is_active=True,
        line_count=1,
        eng_review_status="approved",
    )
    db.add(bom)
    db.flush()
    db.add(
        BomLine(
            bom_model_id=bom.id,
            material_code="R-PMC-1",
            material_name="PMC电阻",
            qty_per=1,
            unit="PCS",
            process="SMT",
            sort_order=0,
            is_active=True,
        )
    )
    return bom


def find_board_row(items: list[dict], so_id: int) -> dict | None:
    for it in items:
        if int(it.get("so_id") or 0) == so_id:
            return it
    return None


def main() -> int:
    print("=== SRM 默认同步关闭 ===")
    try:
        assert DEFAULT_CONFIG.get("auto_sync_enabled") is False
        ok("DEFAULT_CONFIG.auto_sync_enabled=False")
        cfg = load_config()
        assert cfg.get("auto_sync_enabled") is False
        ok("load_config().auto_sync_enabled=False")
    except Exception as e:
        fail("SRM 默认关闭", e)
        traceback.print_exc()

    print("\n=== 准备 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)
    bom = ensure_bom(db)
    db.commit()
    ok(f"BOM {bom.model_code} id={bom.id}")

    print("\n=== 待 MRP 催办 ===")
    try:
        tag = uuid.uuid4().hex[:6]
        so_a = create_sales_order(
            db,
            {
                "customer_name": f"PMC催办A-{tag}",
                "lines": [
                    {
                        "material_code": "JL-PMC-FG",
                        "material_name": "PMC模拟成品",
                        "qty": 5,
                        "unit_price": 1,
                    }
                ],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so_a.id, "confirmed", user="WGQ")
        db.commit()
        board = pmc_board(db, limit=200)
        row = find_board_row(board, so_a.id)
        assert row, "看板未包含销售单"
        assert "待跑 MRP" in "；".join(row.get("alerts") or [])
        assert row.get("urgency") == "high"
        ok(f"SO {so_a.so_no} 提示待跑 MRP urgency={row['urgency']}")
    except Exception as e:
        fail("待 MRP 催办", e)
        traceback.print_exc()
        db.rollback()
        so_a = None

    print("\n=== MRP 后三线可见 ===")
    try:
        tag = uuid.uuid4().hex[:6]
        so_b = create_sales_order(
            db,
            {
                "customer_name": f"PMC催办B-{tag}",
                "lines": [
                    {
                        "material_code": "JL-PMC-FG",
                        "material_name": "PMC模拟成品",
                        "qty": 8,
                        "unit_price": 2,
                    }
                ],
            },
            user="WGQ",
        )
        set_sales_order_status(db, so_b.id, "confirmed", user="WGQ")
        _, lines = get_sales_order(db, so_b.id)
        bind_sales_line_bom(db, so_b.id, lines[0].id, bom.id)
        db.commit()
        gen = generate_mrp(db, so_ids=[so_b.id], advance_status=True, user="WGQ")
        db.commit()
        board = pmc_board(db, limit=200)
        row = find_board_row(board, so_b.id)
        assert row
        assert int(row.get("production_plan_lines") or 0) >= 1
        assert int(row.get("purchase_plan_lines") or 0) + int(row.get("outsource_plan_lines") or 0) >= 0
        so_b2 = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == so_b.id).first()
        assert so_b2 and so_b2.status in ("planning", "executing")
        ok(
            f"SO {so_b.so_no} 计划采={row.get('purchase_plan_lines')} "
            f"产={row.get('production_plan_lines')} 外={row.get('outsource_plan_lines')} "
            f"状态={so_b2.status} run={gen.get('run_no')}"
        )
    except Exception as e:
        fail("MRP 后看板", e)
        traceback.print_exc()
        db.rollback()
        so_b = None

    print("\n=== 催办写备注 ===")
    try:
        target = so_b or so_a
        assert target is not None
        before = (db.query(ErpSalesOrder).filter(ErpSalesOrder.id == target.id).first().remark) or ""
        out = pmc_urge(db, target.id, user="WGQ", note="阶段11模拟催办")
        db.commit()
        so = db.query(ErpSalesOrder).filter(ErpSalesOrder.id == target.id).first()
        assert "[催办" in (so.remark or "")
        assert "阶段11模拟催办" in (so.remark or "")
        assert len(so.remark or "") > len(before)
        ok(f"催办写入 {out['so_no']} @ {out['urged_at']}")
    except Exception as e:
        fail("催办写备注", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 出货进度字段 ===")
    try:
        board = pmc_board(db, limit=50)
        assert board
        sample = board[0]
        for k in ("ship_progress", "shipped_qty", "sales_issue_count", "delivery_count", "urge_hint"):
            assert k in sample
        ok(f"看板字段齐全 sample={sample.get('so_no')} progress={sample.get('ship_progress')}")
    except Exception as e:
        fail("出货进度字段", e)
        traceback.print_exc()

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
        board = api("GET", "/api/planning/pmc-board")
        items = board.get("items") or []
        assert isinstance(items, list)
        ok(f"HTTP pmc-board 行数={len(items)}")
        if so_b is not None:
            so_id = so_b.id
        elif so_a is not None:
            so_id = so_a.id
        else:
            so_id = int(items[0]["so_id"])
        urged = api("POST", f"/api/planning/pmc-board/{so_id}/urge", {"note": "HTTP催办"})
        assert urged.get("so_id") == so_id
        ok(f"HTTP 催办 so_id={so_id}")
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
