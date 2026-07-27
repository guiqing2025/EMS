"""物料管制单 API"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from database import get_db
from material_control_ecn import (
    build_control_payload_from_ecn_preview,
    parse_yonglian_ecn_file,
)
from material_control_parse import parse_control_file
from material_control_service import (
    CONTROL_UPLOAD_DIR,
    build_control_template_xlsx,
    cancel_control,
    confirm_control,
    control_to_dict,
    create_control,
    delete_control,
    get_control,
    get_controls_for_purchase,
    import_controls_from_excel,
    list_controls,
    set_attachment,
    update_draft,
)
from pydantic import BaseModel, Field
from schemas import MaterialControlCreateIn, MaterialControlUpdateIn
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/material-controls",
    tags=["material-controls"],
    dependencies=[Depends(require_system_auth)],
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")
CONTROL_ACTION_PASSWORD = "dxdx888"


class ControlPasswordAction(BaseModel):
    password: str = Field(..., description="撤销/删除操作密码")


def _require_action_password(password: str) -> None:
    if (password or "").strip() != CONTROL_ACTION_PASSWORD:
        raise HTTPException(status_code=403, detail="密码错误，无法撤销或删除")


def _actor_label(principal: AuthPrincipal) -> str:
    """显示名 + 登录帐号，便于事后追溯谁录入/确认。"""
    name = (principal.display_name or "").strip()
    user = (principal.username or "").strip()
    if name and user and name != user:
        return f"{name}（{user}）"
    return name or user or ""


def _require_editor(principal: AuthPrincipal) -> AuthPrincipal:
    if principal.role not in ("admin", "planner", "engineering"):
        raise HTTPException(status_code=403, detail="无物料管制编辑权限")
    return principal


@router.get("")
def api_list_controls(
    status: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
):
    return list_controls(db, status=status, keyword=keyword)


@router.get("/by-purchase/{purchase_no}")
def api_controls_by_purchase(
    purchase_no: str,
    model_code: str = "",
    db: Session = Depends(get_db),
):
    return get_controls_for_purchase(db, purchase_no, model_code=model_code)


@router.get("/template.xlsx")
def api_download_template(principal: AuthPrincipal = Depends(require_system_auth)):
    _require_editor(principal)
    content = build_control_template_xlsx()
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="material_control_template.xlsx"'},
    )


@router.post("/parse")
async def api_parse_control_file(
    file: UploadFile = File(...),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """识别 PDF/图片并返回预填字段（不落库、不改 BOM）。"""
    _require_editor(principal)
    content = await file.read()
    try:
        return parse_control_file(file.filename or "upload.bin", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"识别失败：{exc}") from exc


@router.post("/import-excel")
async def api_import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_editor(principal)
    name = (file.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx）")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        result = import_controls_from_excel(
            db,
            content,
            created_by=_actor_label(principal),
            source_name=file.filename or "",
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parse-ecn")
async def api_parse_ecn(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """解析永联 ECR/ECN 变更单，返回预览（含匹配在制订单，默认全选）。"""
    _require_editor(principal)
    name = (file.filename or "").lower()
    if not name.endswith((".xls", ".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传永联 ECN 表格（.xls / .xlsx）")
    content = await file.read()
    try:
        return parse_yonglian_ecn_file(db, file.filename or "ecn.xls", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"解析失败：{exc}") from exc


@router.post("/import-ecn")
async def api_import_ecn(
    file: UploadFile = File(...),
    selected_purchase_nos: str = Form(""),
    control_no: str = Form(""),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """解析永联 ECN 并创建管制草稿，同时保存原表为附件。"""
    _require_editor(principal)
    name = (file.filename or "").lower()
    if not name.endswith((".xls", ".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传永联 ECN 表格（.xls / .xlsx）")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    selected = [p.strip() for p in (selected_purchase_nos or "").split(",") if p.strip()]
    try:
        preview = parse_yonglian_ecn_file(db, file.filename or "ecn.xls", content)
        payload = build_control_payload_from_ecn_preview(
            db,
            preview,
            selected_purchase_nos=selected or None,
            control_no=(control_no or "").strip(),
        )
        row = create_control(db, payload, created_by=_actor_label(principal))
        db.flush()
        # 附件
        CONTROL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        raw_name = (file.filename or "ecn.xls").strip() or "ecn.xls"
        safe = _SAFE_NAME.sub("_", raw_name)[:180]
        stored = f"{row.id}_{uuid.uuid4().hex[:10]}_{safe}"
        dest = CONTROL_UPLOAD_DIR / stored
        dest.write_bytes(content)
        set_attachment(db, row.id, f"uploads/controls/{stored}", raw_name)
        db.commit()
        db.refresh(row)
        return {
            "ok": True,
            "message": f"已生成管制草稿 {row.control_no}",
            "control": control_to_dict(db, row),
            "preview_warnings": preview.get("warnings") or [],
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=400, detail=f"导入失败：{exc}") from exc


@router.get("/{control_id}")
def api_get_control(control_id: int, db: Session = Depends(get_db)):
    try:
        row = get_control(db, control_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return control_to_dict(db, row)


@router.post("")
def api_create_control(
    body: MaterialControlCreateIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_editor(principal)
    try:
        row = create_control(
            db,
            body.model_dump(),
            created_by=_actor_label(principal),
        )
        db.commit()
        db.refresh(row)
        return control_to_dict(db, row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{control_id}")
def api_update_control(
    control_id: int,
    body: MaterialControlUpdateIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_editor(principal)
    try:
        row = update_draft(db, control_id, body.model_dump(exclude_unset=True))
        db.commit()
        db.refresh(row)
        return control_to_dict(db, row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{control_id}/attachment")
async def api_upload_attachment(
    control_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_editor(principal)
    raw_name = (file.filename or "attachment").strip() or "attachment"
    safe = _SAFE_NAME.sub("_", raw_name)[:180]
    CONTROL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{control_id}_{uuid.uuid4().hex[:10]}_{safe}"
    dest = CONTROL_UPLOAD_DIR / stored
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空文件")
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="附件过大（上限 30MB）")
    dest.write_bytes(content)
    rel = f"uploads/controls/{stored}"
    try:
        row = set_attachment(db, control_id, rel, raw_name)
        db.commit()
        db.refresh(row)
        return control_to_dict(db, row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{control_id}/attachment")
def api_download_attachment(control_id: int, db: Session = Depends(get_db)):
    try:
        row = get_control(db, control_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not row.attachment_path:
        raise HTTPException(status_code=404, detail="无附件")
    path = Path(__file__).resolve().parent.parent / "static" / row.attachment_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="附件文件不存在")
    return FileResponse(
        path,
        filename=row.attachment_name or path.name,
    )


@router.post("/{control_id}/confirm")
def api_confirm_control(
    control_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_editor(principal)
    try:
        row = confirm_control(
            db,
            control_id,
            confirmed_by=_actor_label(principal),
        )
        db.commit()
        db.refresh(row)
        payload = control_to_dict(db, row)
        payload["confirm_applied"] = list(getattr(row, "_confirm_applied", []) or [])
        payload["confirm_skipped_inactive"] = list(
            getattr(row, "_confirm_skipped_inactive", []) or []
        )
        payload["confirm_skipped_no_bom"] = list(getattr(row, "_confirm_skipped_no_bom", []) or [])
        return payload
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{control_id}/cancel")
def api_cancel_control(
    control_id: int,
    payload: ControlPasswordAction,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_editor(principal)
    _require_action_password(payload.password)
    try:
        row = cancel_control(
            db,
            control_id,
            cancelled_by=_actor_label(principal),
        )
        db.commit()
        db.refresh(row)
        return control_to_dict(db, row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{control_id}/delete")
def api_delete_control(
    control_id: int,
    payload: ControlPasswordAction,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_editor(principal)
    _require_action_password(payload.password)
    try:
        result = delete_control(db, control_id)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
