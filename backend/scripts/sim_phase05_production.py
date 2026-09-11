#!/usr/bin/env python3
"""阶段5验收：生产单→BOM领料→QA→成品入库；不合格禁入库。

用法:
  EMS_DB=ems.dev.db EMS_USE_SQLITE=1 .venv/bin/python scripts/sim_phase05_production.py
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
from models import BomLine, BomModel, WarehouseMaterial  # noqa: E402
from production_service import (  # noqa: E402
    confirm_material_doc,
    create_fg_from_qa,
    create_material_doc,
    create_mo,
    create_qa_from_mo,
    get_mo,
    judge_qa,
    post_fg,
    register_barcode,
    set_mo_status,
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


def stock(db, code: str, owner: str = "internal") -> float:
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
    print("=== 准备 BOM+库存 ===")
    migrate()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    ensure_default_users(db)

    bom = db.query(BomModel).filter(BomModel.model_code == "JL-MO-FG", BomModel.purchase_no == "MO-SIM").first()
    if not bom:
        bom = BomModel(
            internal_code="MO1",
            customer_id="internal",
            customer_name="内部",
            model_code="JL-MO-FG",
            purchase_no="MO-SIM",
            model_name="生产模拟成品",
            is_active=True,
            line_count=1,
            eng_review_status="approved",
        )
        db.add(bom)
        db.flush()
        db.add(
            BomLine(
                bom_model_id=bom.id,
                material_code="R-MO-001",
                material_name="生产用电阻",
                qty_per=2,
                unit="PCS",
                is_active=True,
            )
        )
    bom_id = int(bom.id)
    ensure_mat(db, "R-MO-001", 500, "生产用电阻")
    db.commit()
    ok(f"BOM#{bom_id} 元件库存就绪")

    print("\n=== 合格闭环 ===")
    try:
        mo = create_mo(
            db,
            {
                "material_code": "JL-MO-FG",
                "material_name": "生产模拟成品",
                "qty": 10,
                "bom_model_id": bom_id,
            },
            user="WGQ",
        )
        set_mo_status(db, mo.id, "released", user="WGQ")
        register_barcode(db, mo.id, f"MOBC-{uuid.uuid4().hex[:8]}", user="WGQ")
        db.commit()
        ok(f"生产单 {mo.mo_no} released+条码")

        before = stock(db, "R-MO-001")
        doc = create_material_doc(db, mo_id=mo.id, kind="issue", from_bom=True, user="WGQ")
        confirm_material_doc(db, doc.id, user="WGQ")
        db.commit()
        after = stock(db, "R-MO-001")
        assert after == before - 20, (before, after)
        ok(f"BOM领料 {doc.doc_no} 扣料 20")

        qa = create_qa_from_mo(db, mo.id, user="WGQ")
        judge_qa(db, qa.id, pass_qty=10, fail_qty=0, user="WGQ")
        db.commit()
        ok(f"QA pass {qa.qa_no}")

        fg_before = stock(db, "JL-MO-FG")
        fg = create_fg_from_qa(db, qa.id, user="WGQ", direct_outbound=True)
        post_fg(db, fg.id, user="WGQ")
        db.commit()
        mo2 = get_mo(db, mo.id)
        assert stock(db, "JL-MO-FG") == fg_before + 10
        assert mo2.status == "fg_done"
        assert fg.direct_outbound is True
        ok(f"成品入库 {fg.receipt_no} MO→{mo2.status} direct_outbound")
    except Exception as e:
        fail("合格闭环", e)
        traceback.print_exc()
        db.rollback()

    print("\n=== 负向：QA 不合格禁入库 ===")
    try:
        mo = create_mo(
            db,
            {"material_code": "JL-MO-FG", "material_name": "生产模拟成品", "qty": 5, "bom_model_id": bom_id},
            user="WGQ",
        )
        set_mo_status(db, mo.id, "released", user="WGQ")
        create_material_doc(db, mo_id=mo.id, kind="issue", from_bom=True, user="WGQ")
        # need confirm to get to in_process - create_material sets issuing, confirm sets in_process
        from production_service import list_material_docs, get_material_doc

        docs = list_material_docs(db, mo_id=mo.id)
        confirm_material_doc(db, docs[0].id, user="WGQ")
        qa = create_qa_from_mo(db, mo.id, user="WGQ")
        judge_qa(db, qa.id, pass_qty=0, fail_qty=5, user="WGQ")
        db.commit()
        try:
            create_fg_from_qa(db, qa.id, user="WGQ")
            fail("不合格应禁止成品入库")
            db.rollback()
        except ValueError as ve:
            ok(f"负向：{ve}")
            db.rollback()
    except Exception as e:
        fail("负向", e)
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
        mo = api(
            "POST",
            "/api/production/orders",
            {"material_code": "JL-MO-FG", "material_name": "生产模拟成品", "qty": 2, "bom_model_id": bom_id},
        )
        api("POST", f"/api/production/orders/{mo['id']}/status", {"status": "released"})
        api("POST", f"/api/production/orders/{mo['id']}/barcodes", {"barcode": f"H-{uuid.uuid4().hex[:8]}"})
        doc = api("POST", "/api/production/materials", {"mo_id": mo["id"], "kind": "issue", "from_bom": True})
        api("POST", f"/api/production/materials/{doc['id']}/confirm")
        qa = api("POST", f"/api/production/qa/from-mo/{mo['id']}")
        api("POST", f"/api/production/qa/{qa['id']}/judge", {"pass_qty": 2, "fail_qty": 0})
        fg = api("POST", f"/api/production/fg-receipts/from-qa/{qa['id']}", {"direct_outbound": False})
        api("POST", f"/api/production/fg-receipts/{fg['id']}/post")
        board = api("GET", "/api/production/pmc-board")
        ok(f"HTTP 闭环 {mo['mo_no']}→{fg['receipt_no']} PMC={len(board.get('items') or [])}")
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
