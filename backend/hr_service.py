"""人事业务：员工档案维护、请假登记。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import HrEmployee, HrLeaveRecord

HIRE_GRADES = ("A", "B", "C", "D")
LEAVE_TYPES = ("事假", "病假", "年假", "婚假", "产假", "丧假", "调休", "其他")
LEAVE_REASONS_PRESET = (
    "个人发展",
    "家庭原因",
    "薪资待遇",
    "工作环境",
    "合同到期",
    "试用不合格",
    "违纪辞退",
    "其他",
)


def _today() -> str:
    return date.today().isoformat()


def _norm_emp_no(value: str) -> str:
    return (value or "").strip().upper()


def _calc_days(start: str, end: str) -> float:
    try:
        s = date.fromisoformat(start[:10])
        e = date.fromisoformat(end[:10])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    if e < s:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
    return float((e - s).days + 1)


def get_employee(db: Session, employee_id: int) -> HrEmployee:
    row = db.query(HrEmployee).filter(HrEmployee.id == employee_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="员工不存在")
    return row


def create_employee(db: Session, data: dict) -> HrEmployee:
    emp_no = _norm_emp_no(data.get("employee_no") or "")
    name = (data.get("name") or "").strip()
    if not emp_no or not name:
        raise HTTPException(status_code=400, detail="工号和姓名必填")
    exists = db.query(HrEmployee).filter(HrEmployee.employee_no == emp_no).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"工号已存在: {emp_no}")

    hire_grade = (data.get("hire_grade") or "").strip().upper() or None
    if hire_grade and hire_grade not in HIRE_GRADES:
        raise HTTPException(status_code=400, detail=f"入职评审等级应为 {', '.join(HIRE_GRADES)}")

    now = datetime.utcnow()
    lives = bool(data.get("lives_in_dorm"))
    row = HrEmployee(
        employee_no=emp_no,
        name=name,
        gender=(data.get("gender") or None),
        id_card=(data.get("id_card") or None),
        phone=(data.get("phone") or None),
        address=(data.get("address") or None),
        hire_date=(data.get("hire_date") or _today()),
        department=(data.get("department") or None),
        position=(data.get("position") or None),
        education=(data.get("education") or None),
        remark=(data.get("remark") or None),
        hire_grade=hire_grade,
        lives_in_dorm=lives,
        dorm_room=(data.get("dorm_room") or None) if lives else None,
        source="manual",
        status_locked=True,
        is_active=True,
        leave_date=None,
        leave_reason=None,
        synced_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_employee(db: Session, employee_id: int, data: dict) -> HrEmployee:
    row = get_employee(db, employee_id)
    now = datetime.utcnow()

    if "employee_no" in data and data["employee_no"] is not None:
        new_no = _norm_emp_no(str(data["employee_no"]))
        if new_no and new_no != row.employee_no:
            clash = (
                db.query(HrEmployee)
                .filter(HrEmployee.employee_no == new_no, HrEmployee.id != row.id)
                .first()
            )
            if clash:
                raise HTTPException(status_code=400, detail=f"工号已存在: {new_no}")
            row.employee_no = new_no

    text_fields = (
        "name",
        "gender",
        "id_card",
        "phone",
        "address",
        "hire_date",
        "department",
        "position",
        "education",
        "remark",
        "dorm_room",
    )
    for key in text_fields:
        if key in data:
            val = data[key]
            if isinstance(val, str):
                val = val.strip() or None
            setattr(row, key, val)

    if "hire_grade" in data:
        grade = (data.get("hire_grade") or "").strip().upper() or None
        if grade and grade not in HIRE_GRADES:
            raise HTTPException(status_code=400, detail=f"入职评审等级应为 {', '.join(HIRE_GRADES)}")
        row.hire_grade = grade

    if "lives_in_dorm" in data:
        row.lives_in_dorm = bool(data.get("lives_in_dorm"))
        if not row.lives_in_dorm:
            row.dorm_room = None

    if row.lives_in_dorm and not (row.dorm_room or "").strip():
        # 允许暂空宿舍号，但前端会提示
        pass

    row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def resign_employee(
    db: Session,
    employee_id: int,
    *,
    leave_date: Optional[str],
    leave_reason: str,
) -> HrEmployee:
    row = get_employee(db, employee_id)
    reason = (leave_reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="请填写离职原因")
    row.is_active = False
    row.leave_date = (leave_date or "").strip() or _today()
    row.leave_reason = reason
    row.status_locked = True
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def rehire_employee(
    db: Session,
    employee_id: int,
    *,
    hire_date: Optional[str] = None,
    hire_grade: Optional[str] = None,
    clear_leave: bool = True,
) -> HrEmployee:
    row = get_employee(db, employee_id)
    row.is_active = True
    row.status_locked = True
    if hire_date:
        row.hire_date = hire_date.strip()
    if hire_grade is not None:
        grade = (hire_grade or "").strip().upper() or None
        if grade and grade not in HIRE_GRADES:
            raise HTTPException(status_code=400, detail=f"入职评审等级应为 {', '.join(HIRE_GRADES)}")
        row.hire_grade = grade
    if clear_leave:
        row.leave_date = None
        row.leave_reason = None
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def list_leaves(
    db: Session,
    *,
    keyword: str = "",
    leave_type: str = "",
    status: str = "all",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[int, list[HrLeaveRecord]]:
    q = db.query(HrLeaveRecord)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            or_(
                HrLeaveRecord.employee_no.ilike(like),
                HrLeaveRecord.employee_name.ilike(like),
                HrLeaveRecord.reason.ilike(like),
            )
        )
    lt = (leave_type or "").strip()
    if lt:
        q = q.filter(HrLeaveRecord.leave_type == lt)
    st = (status or "all").strip()
    if st in ("approved", "cancelled"):
        q = q.filter(HrLeaveRecord.status == st)
    df = (date_from or "").strip()
    if df:
        q = q.filter(HrLeaveRecord.end_date >= df)
    dt = (date_to or "").strip()
    if dt:
        q = q.filter(HrLeaveRecord.start_date <= dt)

    total = q.count()
    rows = (
        q.order_by(HrLeaveRecord.start_date.desc(), HrLeaveRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, rows


def create_leave(db: Session, data: dict, *, created_by: str = "") -> HrLeaveRecord:
    employee_id = int(data.get("employee_id") or 0)
    emp = get_employee(db, employee_id)
    leave_type = (data.get("leave_type") or "事假").strip()
    if leave_type not in LEAVE_TYPES:
        raise HTTPException(status_code=400, detail=f"请假类型无效，可选: {', '.join(LEAVE_TYPES)}")
    start_date = (data.get("start_date") or "").strip()
    end_date = (data.get("end_date") or "").strip() or start_date
    if not start_date:
        raise HTTPException(status_code=400, detail="请选择请假开始日期")
    days = data.get("days")
    if days is None or days == "":
        days = _calc_days(start_date, end_date)
    else:
        days = float(days)
        if days <= 0:
            raise HTTPException(status_code=400, detail="请假天数须大于 0")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="请填写请假原因")

    now = datetime.utcnow()
    row = HrLeaveRecord(
        employee_id=emp.id,
        employee_no=emp.employee_no,
        employee_name=emp.name,
        leave_type=leave_type,
        start_date=start_date[:10],
        end_date=end_date[:10],
        days=days,
        reason=reason,
        status="approved",
        created_by=created_by or None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def cancel_leave(db: Session, leave_id: int) -> HrLeaveRecord:
    row = db.query(HrLeaveRecord).filter(HrLeaveRecord.id == leave_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    row.status = "cancelled"
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def delete_leave(db: Session, leave_id: int) -> None:
    row = db.query(HrLeaveRecord).filter(HrLeaveRecord.id == leave_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="请假记录不存在")
    db.delete(row)
    db.commit()
