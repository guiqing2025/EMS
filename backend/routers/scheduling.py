from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import ProductionSchedule
from schemas import ScheduleImportOrderIn, ScheduleIn, ScheduleOut, ScheduleReorderIn
from scheduling_service import (
    MATERIAL_STATUS_LABELS,
    SCHEDULE_STATUS_LABELS,
    TOOLING_STATUS_LABELS,
    create_schedule,
    delete_schedule,
    import_from_order,
    list_schedules,
    reorder_schedules,
    refresh_material_status,
    schedule_to_dict,
    update_schedule,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(prefix="/api/scheduling", tags=["scheduling"], dependencies=[Depends(require_system_auth)])


def _require_planner(principal: AuthPrincipal) -> None:
    if principal.role not in ("admin", "planner"):
        raise HTTPException(status_code=403, detail="无排产模块权限")


def _serialize(row: ProductionSchedule, db: Session) -> ScheduleOut:
    return ScheduleOut(**schedule_to_dict(db, row))


@router.get("/meta")
def meta():
    return {
        "material_statuses": MATERIAL_STATUS_LABELS,
        "schedule_statuses": SCHEDULE_STATUS_LABELS,
        "tooling_statuses": TOOLING_STATUS_LABELS,
    }


@router.get("", response_model=list[ScheduleOut])
def get_schedules(line_type: str = "smt", db: Session = Depends(get_db)):
    if line_type not in ("smt", "dip"):
        raise HTTPException(status_code=400, detail="line_type 须为 smt 或 dip")
    return [schedule_to_dict(db, row) for row in list_schedules(db, line_type)]


@router.post("", response_model=ScheduleOut)
def add_schedule(
    body: ScheduleIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    if body.line_type not in ("smt", "dip"):
        raise HTTPException(status_code=400, detail="line_type 须为 smt 或 dip")
    row = create_schedule(db, body.model_dump(), principal.display_name or principal.username)
    db.commit()
    return _serialize(row, db)


@router.put("/{schedule_id}", response_model=ScheduleOut)
def edit_schedule(
    schedule_id: int,
    body: ScheduleIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        row = update_schedule(db, schedule_id, body.model_dump(exclude_unset=True), principal.display_name or principal.username)
        db.commit()
        return _serialize(row, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{schedule_id}")
def remove_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        delete_schedule(db, schedule_id)
        db.commit()
        return {"message": "已删除"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reorder")
def reorder(
    body: ScheduleReorderIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    reorder_schedules(db, body.line_type, body.ids)
    db.commit()
    return {"message": "排序已更新"}


@router.post("/import-order", response_model=ScheduleOut)
def import_order(
    body: ScheduleImportOrderIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        row = import_from_order(db, body.line_key, body.line_type, principal.display_name or principal.username)
        db.commit()
        return _serialize(row, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/refresh-kitting")
def refresh_all_kitting(
    line_type: str = "smt",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    rows = list_schedules(db, line_type)
    for row in rows:
        row.material_status = refresh_material_status(db, row)
    db.commit()
    return {"message": f"已刷新 {len(rows)} 行备料状态"}
