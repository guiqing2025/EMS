"""物料贴装主数据：一次确认；internal_code 空=全局，非空=客户优先覆盖。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import MaterialMountProfile

VALID_TYPES = frozenset({"SMT", "DIP", "ASSY", "N/A"})


def _norm(code: str) -> str:
    from engineering_service import normalize_code

    return normalize_code(code or "")


def _scope(internal_code: str = "") -> str:
    return (internal_code or "").strip().upper()


def load_mount_overrides(db: Session, internal_code: str = "") -> dict[str, dict[str, str]]:
    """料号 -> {mount_type, mount_side}。客户专属优先于全局。"""
    scope = _scope(internal_code)
    rows = db.query(MaterialMountProfile).all()
    global_map: dict[str, dict[str, str]] = {}
    scoped_map: dict[str, dict[str, str]] = {}

    def _put(target: dict, row: MaterialMountProfile) -> None:
        mt = (row.mount_type or "").strip().upper()
        if mt not in VALID_TYPES:
            return
        side = (row.mount_side or "").strip().upper()
        if side and side not in ("TOP", "BOT", "TOP+BOT"):
            side = ""
        payload = {"mount_type": mt, "mount_side": side}
        key = _norm(row.material_code)
        if key:
            target[key] = payload
        raw = (row.material_code or "").strip().upper()
        if raw:
            target[raw] = payload

    for row in rows:
        row_scope = _scope(getattr(row, "internal_code", "") or "")
        if row_scope:
            if scope and row_scope == scope:
                _put(scoped_map, row)
        else:
            _put(global_map, row)

    out = dict(global_map)
    out.update(scoped_map)
    return out


def get_mount_profile(
    db: Session,
    material_code: str,
    internal_code: str = "",
) -> Optional[MaterialMountProfile]:
    key = _norm(material_code)
    if not key:
        return None
    scope = _scope(internal_code)
    rows = db.query(MaterialMountProfile).all()
    scoped_hit = None
    global_hit = None
    for row in rows:
        if _norm(row.material_code) != key:
            continue
        row_scope = _scope(getattr(row, "internal_code", "") or "")
        if scope and row_scope == scope:
            scoped_hit = row
        elif not row_scope:
            global_hit = row
    return scoped_hit or global_hit


def upsert_mount_profile(
    db: Session,
    material_code: str,
    mount_type: str,
    *,
    mount_side: str = "",
    material_name: Optional[str] = None,
    updated_by: Optional[str] = None,
    internal_code: str = "",
) -> MaterialMountProfile:
    code = (material_code or "").strip()
    mt = (mount_type or "").strip().upper()
    scope = _scope(internal_code)
    if not code:
        raise ValueError("料号不能为空")
    if mt not in VALID_TYPES:
        raise ValueError("贴装类型无效，可选：SMT / DIP / ASSY / N/A")
    side = (mount_side or "").strip().upper()
    if side and side not in ("TOP", "BOT", "TOP+BOT"):
        side = ""
    if mt in ("ASSY", "N/A"):
        side = ""

    # 优先精确匹配客户作用域；若库仍仅有全局唯一键，则回退全局行
    row = None
    key = _norm(code)
    for cand in db.query(MaterialMountProfile).all():
        if _norm(cand.material_code) != key:
            continue
        if _scope(getattr(cand, "internal_code", "") or "") == scope:
            row = cand
            break
    if not row and not scope:
        row = get_mount_profile(db, code, "")
    if not row:
        row = MaterialMountProfile(material_code=code, internal_code=scope)
        db.add(row)
    row.material_code = code
    if hasattr(row, "internal_code"):
        row.internal_code = scope
    row.material_name = (material_name or row.material_name or "")[:256] or None
    row.mount_type = mt
    row.mount_side = side or None
    row.source = "manual"
    row.updated_by = (updated_by or "")[:64] or None
    row.updated_at = datetime.utcnow()
    db.flush()
    return row


def list_unresolved_mount_lines(db: Session, bom_model_id: int) -> list[dict]:
    """列出当前 BOM 中仍无 SMT/DIP/ASSY/N/A 的行。"""
    from models import BomLine, BomModel
    from mount_classification import classify_lines_mount, load_placement_index

    bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
    if not bom:
        raise ValueError("BOM 不存在")
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == bom_model_id, BomLine.is_active.is_(True))
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    placement_index = load_placement_index(db, bom)
    ic = bom.internal_code or ""
    overrides = load_mount_overrides(db, internal_code=ic)
    _, mounts = classify_lines_mount(
        lines,
        placement_index=placement_index,
        profile_override=bom.mount_profile_override,
        master_overrides=overrides,
        internal_code=ic,
    )
    unresolved = []
    for line, mount in zip(lines, mounts):
        if mount.get("mount_type"):
            continue
        unresolved.append(
            {
                "line_id": line.id,
                "material_code": line.material_code,
                "material_name": line.material_name,
                "spec": line.spec,
                "position": line.position,
                "process": line.process,
                "mount_reason": mount.get("mount_reason") or "无法判定贴装类型",
            }
        )
    return unresolved
