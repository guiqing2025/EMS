"""人事管理：员工档案 + 请假"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from hr_roster_sync import (
    get_roster_path,
    list_departments,
    mask_id_card,
    roster_accessible,
    sync_hr_roster,
)
from hr_service import (
    HIRE_GRADES,
    LEAVE_REASONS_PRESET,
    LEAVE_TYPES,
    cancel_leave,
    create_employee,
    create_leave,
    delete_leave,
    list_leaves,
    rehire_employee,
    resign_employee,
    update_employee,
)
from models import HrEmployee, HrLeaveRecord
from system_auth import AuthPrincipal, require_hr

router = APIRouter(
    prefix="/api/hr",
    tags=["hr"],
    dependencies=[Depends(require_hr)],
)


class HrEmployeeOut(BaseModel):
    id: int
    employee_no: str
    name: str
    gender: Optional[str] = None
    id_card: Optional[str] = None
    id_card_masked: Optional[str] = None
    age: Optional[float] = None
    age_band: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    hire_date: Optional[str] = None
    tenure_years: Optional[float] = None
    tenure_band: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    education: Optional[str] = None
    remark: Optional[str] = None
    hire_grade: Optional[str] = None
    leave_date: Optional[str] = None
    leave_reason: Optional[str] = None
    lives_in_dorm: bool = False
    dorm_room: Optional[str] = None
    source: str = "roster"
    status_locked: bool = False
    is_active: bool = True
    synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HrEmployeesPage(BaseModel):
    total: int
    items: list[HrEmployeeOut]


class HrMetaOut(BaseModel):
    roster_path: str
    accessible: bool
    active_count: int = 0
    total_count: int = 0
    dorm_count: int = 0
    last_synced_at: Optional[datetime] = None
    departments: list[str] = []
    hire_grades: list[str] = list(HIRE_GRADES)
    leave_types: list[str] = list(LEAVE_TYPES)
    leave_reason_presets: list[str] = list(LEAVE_REASONS_PRESET)


class HrSyncResult(BaseModel):
    path: str
    parsed: int
    created: int
    updated: int
    inactivated: int
    active_count: int
    dorm_count: int = 0
    dorm_matched: int = 0
    dorm_total: int = 0
    dorm_cleared: int = 0
    dorm_unmatched: list[str] = []
    synced_at: str


class HrEmployeeCreate(BaseModel):
    employee_no: str
    name: str
    gender: Optional[str] = None
    id_card: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    hire_date: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    education: Optional[str] = None
    remark: Optional[str] = None
    hire_grade: Optional[str] = None
    lives_in_dorm: bool = False
    dorm_room: Optional[str] = None


class HrEmployeeUpdate(BaseModel):
    employee_no: Optional[str] = None
    name: Optional[str] = None
    gender: Optional[str] = None
    id_card: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    hire_date: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    education: Optional[str] = None
    remark: Optional[str] = None
    hire_grade: Optional[str] = None
    lives_in_dorm: Optional[bool] = None
    dorm_room: Optional[str] = None


class HrResignBody(BaseModel):
    leave_date: Optional[str] = None
    leave_reason: str = Field(..., min_length=1)


class HrRehireBody(BaseModel):
    hire_date: Optional[str] = None
    hire_grade: Optional[str] = None
    clear_leave: bool = True


class HrLeaveOut(BaseModel):
    id: int
    employee_id: int
    employee_no: str
    employee_name: str
    leave_type: str
    start_date: str
    end_date: str
    days: float
    reason: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class HrLeavesPage(BaseModel):
    total: int
    items: list[HrLeaveOut]


class HrLeaveCreate(BaseModel):
    employee_id: int
    leave_type: str = "事假"
    start_date: str
    end_date: Optional[str] = None
    days: Optional[float] = None
    reason: str = Field(..., min_length=1)


def _to_out(row: HrEmployee) -> HrEmployeeOut:
    return HrEmployeeOut(
        id=row.id,
        employee_no=row.employee_no,
        name=row.name,
        gender=row.gender,
        id_card=row.id_card,
        id_card_masked=mask_id_card(row.id_card),
        age=row.age,
        age_band=row.age_band,
        phone=row.phone,
        address=row.address,
        hire_date=row.hire_date,
        tenure_years=row.tenure_years,
        tenure_band=row.tenure_band,
        department=row.department,
        position=row.position,
        education=row.education,
        remark=row.remark,
        hire_grade=getattr(row, "hire_grade", None),
        leave_date=getattr(row, "leave_date", None),
        leave_reason=getattr(row, "leave_reason", None),
        lives_in_dorm=bool(getattr(row, "lives_in_dorm", False)),
        dorm_room=getattr(row, "dorm_room", None),
        source=getattr(row, "source", None) or "roster",
        status_locked=bool(getattr(row, "status_locked", False)),
        is_active=bool(row.is_active),
        synced_at=row.synced_at,
    )


def _leave_out(row: HrLeaveRecord) -> HrLeaveOut:
    return HrLeaveOut(
        id=row.id,
        employee_id=row.employee_id,
        employee_no=row.employee_no,
        employee_name=row.employee_name,
        leave_type=row.leave_type,
        start_date=row.start_date,
        end_date=row.end_date,
        days=row.days,
        reason=row.reason,
        status=row.status,
        created_by=row.created_by,
        created_at=row.created_at,
    )


@router.get("/employees/meta", response_model=HrMetaOut)
def employees_meta(db: Session = Depends(get_db)):
    path = get_roster_path()
    last = (
        db.query(HrEmployee.synced_at)
        .order_by(HrEmployee.synced_at.desc())
        .limit(1)
        .scalar()
    )
    return HrMetaOut(
        roster_path=str(path),
        accessible=roster_accessible(path),
        active_count=db.query(HrEmployee).filter(HrEmployee.is_active.is_(True)).count(),
        total_count=db.query(HrEmployee).count(),
        dorm_count=db.query(HrEmployee).filter(HrEmployee.lives_in_dorm.is_(True)).count(),
        last_synced_at=last,
        departments=list_departments(db),
    )


@router.get("/employees", response_model=HrEmployeesPage)
def list_employees(
    keyword: str = "",
    department: str = "",
    active: str = Query("all", pattern="^(all|active|inactive)$"),
    dorm: str = Query("all", pattern="^(all|yes|no)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    q = db.query(HrEmployee)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            or_(
                HrEmployee.employee_no.ilike(like),
                HrEmployee.name.ilike(like),
                HrEmployee.phone.ilike(like),
                HrEmployee.id_card.ilike(like),
                HrEmployee.dorm_room.ilike(like),
            )
        )
    dept = (department or "").strip()
    if dept:
        q = q.filter(HrEmployee.department == dept)
    if active == "active":
        q = q.filter(HrEmployee.is_active.is_(True))
    elif active == "inactive":
        q = q.filter(HrEmployee.is_active.is_(False))
    if dorm == "yes":
        q = q.filter(HrEmployee.lives_in_dorm.is_(True))
    elif dorm == "no":
        q = q.filter(HrEmployee.lives_in_dorm.is_(False))

    total = q.count()
    rows = (
        q.order_by(HrEmployee.is_active.desc(), HrEmployee.employee_no.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return HrEmployeesPage(total=total, items=[_to_out(r) for r in rows])


@router.post("/employees/sync", response_model=HrSyncResult)
def sync_employees(db: Session = Depends(get_db)):
    try:
        result = sync_hr_roster(db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"同步失败: {exc}") from exc
    return HrSyncResult(**result)


@router.get("/employees/{employee_id}", response_model=HrEmployeeOut)
def get_employee_detail(employee_id: int, db: Session = Depends(get_db)):
    row = db.query(HrEmployee).filter(HrEmployee.id == employee_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="员工不存在")
    return _to_out(row)


@router.post("/employees", response_model=HrEmployeeOut)
def api_create_employee(body: HrEmployeeCreate, db: Session = Depends(get_db)):
    row = create_employee(db, body.model_dump())
    return _to_out(row)


@router.patch("/employees/{employee_id}", response_model=HrEmployeeOut)
def api_update_employee(employee_id: int, body: HrEmployeeUpdate, db: Session = Depends(get_db)):
    row = update_employee(db, employee_id, body.model_dump(exclude_unset=True))
    return _to_out(row)


@router.post("/employees/{employee_id}/resign", response_model=HrEmployeeOut)
def api_resign(employee_id: int, body: HrResignBody, db: Session = Depends(get_db)):
    row = resign_employee(
        db,
        employee_id,
        leave_date=body.leave_date,
        leave_reason=body.leave_reason,
    )
    return _to_out(row)


@router.post("/employees/{employee_id}/rehire", response_model=HrEmployeeOut)
def api_rehire(employee_id: int, body: HrRehireBody = HrRehireBody(), db: Session = Depends(get_db)):
    row = rehire_employee(
        db,
        employee_id,
        hire_date=body.hire_date,
        hire_grade=body.hire_grade,
        clear_leave=body.clear_leave,
    )
    return _to_out(row)


@router.get("/leaves", response_model=HrLeavesPage)
def api_list_leaves(
    keyword: str = "",
    leave_type: str = "",
    status: str = Query("all", pattern="^(all|approved|cancelled)$"),
    date_from: str = "",
    date_to: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    total, rows = list_leaves(
        db,
        keyword=keyword,
        leave_type=leave_type,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return HrLeavesPage(total=total, items=[_leave_out(r) for r in rows])


@router.post("/leaves", response_model=HrLeaveOut)
def api_create_leave(
    body: HrLeaveCreate,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_hr),
):
    row = create_leave(
        db,
        body.model_dump(),
        created_by=principal.display_name or principal.username,
    )
    return _leave_out(row)


@router.post("/leaves/{leave_id}/cancel", response_model=HrLeaveOut)
def api_cancel_leave(leave_id: int, db: Session = Depends(get_db)):
    return _leave_out(cancel_leave(db, leave_id))


@router.delete("/leaves/{leave_id}")
def api_delete_leave(leave_id: int, db: Session = Depends(get_db)):
    delete_leave(db, leave_id)
    return {"ok": True}
