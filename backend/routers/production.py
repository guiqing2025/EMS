"""生产执行链 API"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from production_service import (
    barcode_to_dict,
    confirm_material_doc,
    create_fg_from_qa,
    create_material_doc,
    create_mo,
    create_mo_from_plan,
    create_qa_from_mo,
    fg_to_dict,
    get_fg,
    get_material_doc,
    get_mo,
    get_qa,
    judge_qa,
    list_barcodes,
    list_fg,
    list_material_docs,
    list_mos,
    list_qas,
    material_doc_to_dict,
    mo_to_dict,
    pmc_mo_board,
    post_fg,
    qa_to_dict,
    register_barcode,
    set_mo_status,
)
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/production",
    tags=["production"],
    dependencies=[Depends(require_system_auth)],
)

PROD_ROLES = frozenset({"admin", "production", "pmc", "planner", "quality", "warehouse"})


def require_prod(principal: AuthPrincipal = Depends(require_system_auth)) -> AuthPrincipal:
    name = (principal.username or "").strip().lower()
    if principal.role in PROD_ROLES or name in {"wgq", "dx001"}:
        return principal
    raise HTTPException(status_code=403, detail="无生产模块权限")


class MoIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"
    due_date: str = ""
    bom_model_id: Optional[int] = None
    source_so_id: Optional[int] = None
    source_so_no: str = ""
    stock_owner: str = "internal"
    remark: str = ""


class StatusIn(BaseModel):
    status: str


class FromPlanIn(BaseModel):
    line_id: Optional[int] = None


class BarcodeIn(BaseModel):
    barcode: str
    remark: str = ""


class MaterialLineIn(BaseModel):
    material_code: str = ""
    material_name: str = ""
    qty: float = 0
    unit: str = "PCS"
    remark: str = ""


class MaterialDocIn(BaseModel):
    mo_id: int
    kind: str = "issue"
    from_bom: bool = False
    remark: str = ""
    lines: list[MaterialLineIn] = Field(default_factory=list)


class JudgeQaIn(BaseModel):
    pass_qty: float = 0
    fail_qty: float = 0


class FgFromQaIn(BaseModel):
    direct_outbound: bool = False


def _dump(m: BaseModel) -> dict[str, Any]:
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()  # type: ignore[attr-defined]


@router.get("/orders")
def api_list_mo(
    q: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_prod),
):
    return {"items": [mo_to_dict(r) for r in list_mos(db, q=q, status=status)]}


@router.post("/orders")
def api_create_mo(body: MoIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)):
    try:
        row = create_mo(db, _dump(body), user=principal.username)
        db.commit()
        return mo_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/orders/{mo_id}")
def api_get_mo(mo_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_prod)):
    try:
        return mo_to_dict(get_mo(db, mo_id))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/orders/{mo_id}/status")
def api_mo_status(
    mo_id: int, body: StatusIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)
):
    try:
        row = set_mo_status(db, mo_id, body.status, user=principal.username)
        db.commit()
        return mo_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/orders/from-plan/{plan_id}")
def api_from_plan(
    plan_id: int, body: FromPlanIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)
):
    try:
        rows = create_mo_from_plan(db, plan_id, line_id=body.line_id, user=principal.username)
        db.commit()
        return {"items": [mo_to_dict(r) for r in rows]}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/orders/{mo_id}/barcodes")
def api_barcode(
    mo_id: int, body: BarcodeIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)
):
    try:
        row = register_barcode(db, mo_id, body.barcode, user=principal.username, remark=body.remark)
        db.commit()
        return barcode_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/orders/{mo_id}/barcodes")
def api_list_bc(mo_id: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_prod)):
    return {"items": [barcode_to_dict(r) for r in list_barcodes(db, mo_id)]}


@router.post("/materials")
def api_create_mat(
    body: MaterialDocIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)
):
    try:
        row = create_material_doc(
            db,
            mo_id=body.mo_id,
            kind=body.kind,
            lines=[_dump(x) for x in body.lines] if body.lines else None,
            from_bom=body.from_bom,
            user=principal.username,
            remark=body.remark,
        )
        db.commit()
        row, lines = get_material_doc(db, row.id)
        return material_doc_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/materials")
def api_list_mat(
    kind: str = Query(""),
    mo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: AuthPrincipal = Depends(require_prod),
):
    items = []
    for r in list_material_docs(db, kind=kind, mo_id=mo_id):
        _, lines = get_material_doc(db, r.id)
        items.append(material_doc_to_dict(r, lines))
    return {"items": items}


@router.post("/materials/{doc_id}/confirm")
def api_confirm_mat(
    doc_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)
):
    try:
        confirm_material_doc(db, doc_id, user=principal.username)
        db.commit()
        row, lines = get_material_doc(db, doc_id)
        return material_doc_to_dict(row, lines)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/qa/from-mo/{mo_id}")
def api_create_qa(mo_id: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)):
    try:
        row = create_qa_from_mo(db, mo_id, user=principal.username)
        db.commit()
        return qa_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/qa")
def api_list_qa(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_prod)):
    return {"items": [qa_to_dict(r) for r in list_qas(db)]}


@router.post("/qa/{qa_id}/judge")
def api_judge_qa(
    qa_id: int, body: JudgeQaIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)
):
    try:
        row = judge_qa(db, qa_id, pass_qty=body.pass_qty, fail_qty=body.fail_qty, user=principal.username)
        db.commit()
        return qa_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/fg-receipts/from-qa/{qa_id}")
def api_fg_from_qa(
    qa_id: int, body: FgFromQaIn, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)
):
    try:
        row = create_fg_from_qa(db, qa_id, user=principal.username, direct_outbound=body.direct_outbound)
        db.commit()
        return fg_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/fg-receipts")
def api_list_fg(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_prod)):
    return {"items": [fg_to_dict(r) for r in list_fg(db)]}


@router.post("/fg-receipts/{rid}/post")
def api_post_fg(rid: int, db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_prod)):
    try:
        row = post_fg(db, rid, user=principal.username)
        db.commit()
        return fg_to_dict(row)
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/pmc-board")
def api_pmc(db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_prod)):
    return {"items": pmc_mo_board(db)}
