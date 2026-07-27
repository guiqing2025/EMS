"""机型工序对照（工艺明细.xlsx + 手工勾选）"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from config import get_process_detail_file_path
from engineering_service import normalize_code
from models import BomModel, ModelProcessRoute

PROCESS_STEP_DEFS = [
    {"key": "laser_label", "label": "镭雕/贴码"},
    {"key": "smt", "label": "SMT"},
    {"key": "insert", "label": "插件"},
    {"key": "test", "label": "测试"},
    {
        "key": "conformal",
        "label": "三防",
        "sub_options": ["普通三防", "UV胶"],
    },
    {"key": "potting", "label": "灌胶"},
]


def default_steps() -> dict:
    return {
        "laser_label": False,
        "smt": False,
        "insert": False,
        "test": False,
        "conformal": {"enabled": False, "type": "普通三防"},
        "potting": False,
    }


def _parse_steps_json(raw: Optional[str]) -> dict:
    if not raw:
        return default_steps()
    try:
        data = json.loads(raw)
        base = default_steps()
        for key in ("laser_label", "smt", "insert", "test", "potting"):
            if key in data:
                base[key] = bool(data[key])
        if isinstance(data.get("conformal"), dict):
            base["conformal"] = {
                "enabled": bool(data["conformal"].get("enabled")),
                "type": data["conformal"].get("type") or "普通三防",
            }
        return base
    except (json.JSONDecodeError, TypeError):
        return default_steps()


def steps_to_json(steps: dict) -> str:
    base = default_steps()
    for key in ("laser_label", "smt", "insert", "test", "potting"):
        base[key] = bool(steps.get(key))
    conf = steps.get("conformal") or {}
    base["conformal"] = {
        "enabled": bool(conf.get("enabled")),
        "type": conf.get("type") or "普通三防",
    }
    return json.dumps(base, ensure_ascii=False)


def parse_process_text(text: str) -> dict:
    """将工艺明细表中的工艺字符串解析为勾选状态。"""
    steps = default_steps()
    if not text:
        return steps
    raw = str(text).strip()
    upper = raw.upper()

    if re.search(r"镭雕|贴码", raw):
        steps["laser_label"] = True
    if "SMT" in upper:
        steps["smt"] = True
    if "插件" in raw:
        steps["insert"] = True
    if re.search(r"测试|ICT", raw, re.I):
        steps["test"] = True
    if "灌胶" in raw:
        steps["potting"] = True
    elif "电子胶" in raw and "透明" not in raw:
        steps["potting"] = True

    if "三防" in raw:
        coating_type = "普通三防"
        if re.search(r"UV", raw, re.I):
            coating_type = "UV胶"
        steps["conformal"] = {"enabled": True, "type": coating_type}

    return steps


def build_route_display(steps: dict) -> str:
    parts: list[str] = []
    if steps.get("laser_label"):
        parts.append("镭雕/贴码")
    if steps.get("smt"):
        parts.append("SMT")
    if steps.get("insert"):
        parts.append("插件")
    if steps.get("test"):
        parts.append("测试")
    conf = steps.get("conformal") or {}
    if conf.get("enabled"):
        ctype = conf.get("type") or "普通三防"
        parts.append(f"三防({ctype})" if ctype != "普通三防" else "三防")
    if steps.get("potting"):
        parts.append("灌胶")
    return "-".join(parts)


def _link_bom_model(db: Session, internal_code: str, model_code: str) -> Optional[int]:
    code = normalize_code(model_code)
    row = (
        db.query(BomModel)
        .filter(
            BomModel.internal_code == internal_code.strip().upper(),
            BomModel.is_active.is_(True),
        )
        .all()
    )
    for item in row:
        if normalize_code(item.model_code) == code:
            return item.id
    for item in row:
        mc = normalize_code(item.model_code)
        if mc and (code.startswith(mc) or mc.startswith(code)):
            return item.id
    return None


def route_to_dict(row: ModelProcessRoute) -> dict:
    steps = _parse_steps_json(row.steps_json)
    return {
        "id": row.id,
        "internal_code": row.internal_code,
        "model_code": row.model_code,
        "model_name": row.model_name,
        "bom_model_id": row.bom_model_id,
        "source": row.source,
        "raw_process": row.raw_process,
        "steps": steps,
        "route_display": build_route_display(steps),
        "status": row.status,
        "remark": row.remark,
        "synced_at": row.synced_at,
        "updated_at": row.updated_at,
        "updated_by": row.updated_by,
    }


def get_route(db: Session, internal_code: str, model_code: str) -> Optional[dict]:
    code = normalize_code(model_code)
    ic = internal_code.strip().upper()
    rows = (
        db.query(ModelProcessRoute)
        .filter(ModelProcessRoute.internal_code == ic)
        .all()
    )
    for row in rows:
        if normalize_code(row.model_code) == code:
            return route_to_dict(row)
    return None


def save_route(
    db: Session,
    internal_code: str,
    model_code: str,
    steps: dict,
    *,
    model_name: Optional[str] = None,
    remark: Optional[str] = None,
    operator: Optional[str] = None,
    source: str = "manual",
    raw_process: Optional[str] = None,
) -> dict:
    ic = internal_code.strip().upper()
    code = model_code.strip()
    norm = normalize_code(code)
    row = (
        db.query(ModelProcessRoute)
        .filter(ModelProcessRoute.internal_code == ic)
        .all()
    )
    target = None
    for item in row:
        if normalize_code(item.model_code) == norm:
            target = item
            break
    now = datetime.utcnow()
    bom_id = _link_bom_model(db, ic, code)
    if not target:
        target = ModelProcessRoute(internal_code=ic, model_code=code)
        db.add(target)
    target.model_name = model_name or target.model_name
    target.bom_model_id = bom_id
    target.steps_json = steps_to_json(steps)
    target.source = source
    if raw_process is not None:
        target.raw_process = raw_process
    target.status = "configured" if build_route_display(steps) else "pending"
    target.remark = remark
    target.updated_at = now
    target.updated_by = operator
    if source == "excel" and not target.synced_at:
        target.synced_at = now
    db.flush()
    return route_to_dict(target)


def list_routes(
    db: Session,
    internal_code: str = "",
    keyword: str = "",
    status: str = "",
) -> list[dict]:
    q = db.query(ModelProcessRoute).order_by(
        ModelProcessRoute.internal_code.asc(), ModelProcessRoute.model_code.asc()
    )
    if internal_code:
        q = q.filter(ModelProcessRoute.internal_code == internal_code.strip().upper())
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            (ModelProcessRoute.model_code.like(like))
            | (ModelProcessRoute.model_name.like(like))
            | (ModelProcessRoute.raw_process.like(like))
            | (ModelProcessRoute.remark.like(like))
        )
    if status:
        q = q.filter(ModelProcessRoute.status == status.strip())
    return [route_to_dict(row) for row in q.limit(500).all()]


def sync_from_workbook(db: Session) -> dict:
    from openpyxl import load_workbook

    path = Path(get_process_detail_file_path())
    if not path.is_file():
        return {
            "status": "error",
            "message": f"工艺明细文件不存在: {path}",
            "rows_imported": 0,
            "source_file": str(path),
        }

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        imported = 0
        now = datetime.utcnow()
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or len(row) < 3:
                continue
            internal_code = str(row[0] or "").strip().upper()
            model_code = str(row[1] or "").strip()
            process_text = str(row[2] or "").strip()
            if not internal_code or not model_code:
                continue
            steps = parse_process_text(process_text)
            save_route(
                db,
                internal_code,
                model_code,
                steps,
                source="excel",
                raw_process=process_text,
                operator="system",
            )
            row_obj = (
                db.query(ModelProcessRoute)
                .filter(
                    ModelProcessRoute.internal_code == internal_code,
                    ModelProcessRoute.model_code == model_code,
                )
                .first()
            )
            if row_obj:
                row_obj.synced_at = now
            imported += 1
    finally:
        wb.close()

    return {
        "status": "success",
        "message": f"已同步 {imported} 条工艺明细",
        "rows_imported": imported,
        "source_file": str(path),
        "synced_at": now,
    }
