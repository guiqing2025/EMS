from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional
import logging

from bom_excel import import_bom_bytes
from database import get_db

logger = logging.getLogger(__name__)
from excel_export import (
    bom_export_content_disposition,
    build_bom_xlsx,
    build_kitting_xlsx,
    kitting_export_content_disposition,
)
from engineering_service import (
    auto_bind_orders,
    bind_order_bom,
    bind_orders_to_bom_by_purchase_no,
    clear_bom_model,
    compute_kitting,
    delete_engineering_order,
    engineering_config,
    get_customer_asset_for_bom,
    get_model_process_map,
    list_bom_model_catalog,
    list_bom_order_catalog,
    list_customer_assets_catalog,
    list_gerber_catalog,
    list_placement_catalog,
    order_kitting,
    update_bom_line,
    update_bom_mount_profile,
)
from models import BomLine, BomModel, ModelProcessRoute, PcbGerberPackage, PcbPlacementFile, PcbRefmapFile, SubstitutionRule
from gerber_sync import (
    get_gerber_files,
    get_gerber_meta,
    import_gerber_zip,
    reaudit_gerber_package,
    remove_gerber_file,
)
from engineering_coverage import relink_asset_records, scan_asset_bom_gaps
from mount_classification import classify_lines_mount, load_placement_index, mount_for_line
from engineering_assets import delete_refmap_store_file
from placement_canonical import (
    delete_gerber_package,
    delete_placement_file,
    delete_refmap_file,
)
from placement_sync import (
    get_placement_lines,
    get_placement_meta,
    import_placement_bytes,
)
from refmap_preview import render_refmap_page_png
from refmap_sync import get_refmap_pdf_path, import_refmap_bytes, reaudit_refmap_file
from tooling_service import get_tooling_for_model, list_tooling_catalog, save_tooling
from process_route_service import (
    PROCESS_STEP_DEFS,
    get_route,
    list_routes,
    save_route,
    sync_from_workbook,
)
from schemas import (
    BomImportResult,
    BomLineOut,
    BomLineUpdateIn,
    BomModelLinesOut,
    BomModelListOut,
    BomModelMountProfileIn,
    BomModelOut,
    CustomerAssetOut,
    EngineeringConfigOut,
    GerberAuditOut,
    GerberFileOut,
    GerberImportResult,
    GerberMetaOut,
    GerberPackageOut,
    KittingOut,
    MaterialMountProfileIn,
    MaterialMountProfileOut,
    OrderBindBomIn,
    EngReviewActionIn,
    EngReviewInboxOut,
    ProcessMapOut,
    ProcessRouteMetaOut,
    ProcessRouteOut,
    ProcessRouteSaveIn,
    ProcessRouteSyncResult,
    ProcessStepDefOut,
    PlacementFileOut,
    PlacementImportResult,
    PlacementLineOut,
    PlacementMetaOut,
    RefmapImportResult,
    ToolingCatalogOut,
    ToolingLookupOut,
    ToolingSaveIn,
    SubstitutionImportConfirmIn,
    SubstitutionImportResult,
    SubstitutionMetaOut,
    SubstitutionParseOut,
    SubstitutionRuleCreateIn,
    SubstitutionRuleOut,
    SubstitutionRuleUpdateIn,
    SubstitutionSyncResult,
    UnresolvedMountLineOut,
    MountReadinessOut,
)
from substitution_import import (
    build_template_xlsx,
    confirm_import,
    create_rule,
    delete_rule,
    parse_xlsx_bytes_with_db,
    update_rule,
)
from substitution_service import reload_substitution_cache_from_db
from substitution_sync import sync_substitution_rules
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(prefix="/api/engineering", tags=["engineering"], dependencies=[Depends(require_system_auth)])


def _require_planner(principal: AuthPrincipal) -> None:
    if principal.role not in ("admin", "planner"):
        raise HTTPException(status_code=403, detail="无工程模块编辑权限")


def _require_eng_import(principal: AuthPrincipal) -> None:
    if not principal.can_eng_import:
        raise HTTPException(status_code=403, detail="无工程资料导入权限")


def _require_eng_audit(principal: AuthPrincipal) -> None:
    if not principal.can_eng_audit:
        raise HTTPException(status_code=403, detail="无工程资料审核权限")


ENG_ORDER_DELETE_PASSWORD = "dxgc888"


class EngOrderDeleteIn(BaseModel):
    password: str = Field(..., description="删除订单操作密码")
    internal_code: str = ""
    purchase_no: str
    model_code: str = ""
    bom_model_id: Optional[int] = None


def _require_order_delete_password(password: str) -> None:
    if (password or "").strip() != ENG_ORDER_DELETE_PASSWORD:
        raise HTTPException(status_code=403, detail="操作密码错误")


def _submitter_name(principal: AuthPrincipal) -> str:
    return (principal.display_name or principal.username or "").strip()


def _push_review_after_import(
    db: Session,
    *,
    principal: AuthPrincipal,
    bom_model_id: Optional[int] = None,
    internal_code: str = "",
    model_code: str = "",
    note: str = "",
) -> None:
    from eng_review_service import submit_bom_for_review, submit_by_model_code

    who = _submitter_name(principal)
    if bom_model_id:
        submit_bom_for_review(db, int(bom_model_id), submitter=who, note=note)
    elif internal_code and model_code:
        submit_by_model_code(
            db,
            internal_code=internal_code.strip().upper(),
            model_code=model_code.strip(),
            submitter=who,
            note=note,
        )

def _bom_line_out(line: BomLine, mount: dict[str, str]) -> BomLineOut:
    return BomLineOut(
        id=line.id,
        bom_model_id=line.bom_model_id,
        seq=line.seq,
        material_code=line.material_code,
        material_name=line.material_name,
        spec=line.spec,
        unit=line.unit,
        qty_per=line.qty_per,
        position=line.position,
        process=line.process,
        remark=line.remark,
        sort_order=line.sort_order,
        mount_type=mount["mount_type"],
        mount_side=mount["mount_side"],
        mount_source=mount["mount_source"],
        mount_reason=mount.get("mount_reason") or "",
        is_active=bool(getattr(line, "is_active", True)),
        source=getattr(line, "source", None) or "import",
        control_id=getattr(line, "control_id", None),
    )


@router.get("/config", response_model=EngineeringConfigOut)
def get_config():
    return engineering_config()


@router.get("/coverage")
def engineering_coverage(db: Session = Depends(get_db)):
    return scan_asset_bom_gaps(db)


@router.post("/relink-assets")
def engineering_relink(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_system_auth)):
    _require_planner(principal)
    result = relink_asset_records(db)
    db.commit()
    return result


def _steps_payload(body: ProcessRouteSaveIn) -> dict:
    return {
        "laser_label": body.steps.laser_label,
        "smt": body.steps.smt,
        "insert": body.steps.insert,
        "test": body.steps.test,
        "conformal": {
            "enabled": body.steps.conformal_enabled,
            "type": body.steps.conformal_type or "普通三防",
        },
        "potting": body.steps.potting,
    }


@router.get("/process-routes/steps-def", response_model=list[ProcessStepDefOut])
def process_steps_def():
    return [ProcessStepDefOut(**item) for item in PROCESS_STEP_DEFS]


@router.get("/process-routes/meta", response_model=ProcessRouteMetaOut)
def process_routes_meta(db: Session = Depends(get_db)):
    from config import get_process_detail_file_path
    from pathlib import Path

    path = Path(get_process_detail_file_path())
    count = db.query(ModelProcessRoute).count()
    pending = db.query(ModelProcessRoute).filter(ModelProcessRoute.status == "pending").count()
    latest = db.query(ModelProcessRoute.synced_at).order_by(ModelProcessRoute.id.desc()).first()
    return ProcessRouteMetaOut(
        source_file=str(path),
        source_accessible=path.is_file(),
        row_count=count,
        pending_count=pending,
        synced_at=latest[0] if latest else None,
    )


@router.post("/process-routes/sync-now", response_model=ProcessRouteSyncResult)
def process_routes_sync(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_system_auth)):
    _require_planner(principal)
    result = sync_from_workbook(db)
    db.commit()
    return ProcessRouteSyncResult(**result)


@router.get("/process-routes", response_model=list[ProcessRouteOut])
def process_routes_list(
    internal_code: str = "",
    keyword: str = "",
    status: str = "",
    db: Session = Depends(get_db),
):
    return list_routes(db, internal_code, keyword, status)


@router.get("/process-routes/lookup", response_model=ProcessRouteOut)
def process_route_lookup(
    internal_code: str = Query(...),
    model_code: str = Query(...),
    db: Session = Depends(get_db),
):
    row = get_route(db, internal_code, model_code)
    if not row:
        bom = (
            db.query(BomModel)
            .filter(BomModel.internal_code == internal_code.strip().upper())
            .all()
        )
        model_name = None
        bom_id = None
        from engineering_service import normalize_code
        from process_route_service import default_steps

        norm = normalize_code(model_code)
        for item in bom:
            if normalize_code(item.model_code) == norm:
                model_name = item.model_name
                bom_id = item.id
                break

        return ProcessRouteOut(
            id=0,
            internal_code=internal_code.strip().upper(),
            model_code=model_code.strip(),
            model_name=model_name,
            bom_model_id=bom_id,
            source="manual",
            raw_process=None,
            steps=default_steps(),
            route_display="",
            status="pending",
        )
    return ProcessRouteOut(**row)


@router.put("/process-routes", response_model=ProcessRouteOut)
def process_route_save(
    body: ProcessRouteSaveIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    saved = save_route(
        db,
        body.internal_code,
        body.model_code,
        _steps_payload(body),
        model_name=body.model_name,
        remark=body.remark,
        operator=principal.username,
        source="manual",
    )
    db.commit()
    return ProcessRouteOut(**saved)


@router.get("/tooling/catalog", response_model=list[ToolingCatalogOut])
def tooling_catalog(
    internal_code: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
):
    return list_tooling_catalog(db, internal_code, keyword)


@router.get("/tooling/lookup", response_model=ToolingLookupOut)
def tooling_lookup(
    internal_code: str,
    model_code: str,
    db: Session = Depends(get_db),
):
    if not internal_code.strip() or not model_code.strip():
        raise HTTPException(status_code=400, detail="请提供内部代码和机型料号")
    return get_tooling_for_model(db, internal_code.strip().upper(), model_code.strip())


@router.put("/tooling", response_model=ToolingLookupOut)
def tooling_save(
    body: ToolingSaveIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        result = save_tooling(
            db,
            body.internal_code,
            body.model_code,
            [e.model_dump() for e in body.entries],
            model_name=body.model_name,
            operator=principal.username,
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/customer-assets", response_model=list[CustomerAssetOut])
def customer_assets_list(
    internal_code: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
):
    return list_customer_assets_catalog(db, internal_code, keyword)


@router.get("/models/{model_id}/assets", response_model=CustomerAssetOut)
def model_assets(
    model_id: int,
    db: Session = Depends(get_db),
):
    """当前订单 BOM 的坐标/Gerber/位号图状态（按订单直查，避免机型折叠串单）。"""
    try:
        return get_customer_asset_for_bom(db, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/refmaps/import", response_model=RefmapImportResult)
async def refmaps_import(
    file: UploadFile = File(...),
    internal_code: str = Form(...),
    model_code: str = Form(...),
    bom_model_id: Optional[int] = Form(None),
    purchase_no: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_eng_import(principal)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    from eng_asset_scope import resolve_purchase_no_for_import

    ic = internal_code.strip().upper()
    try:
        pn = resolve_purchase_no_for_import(
            db, internal_code=ic, bom_model_id=bom_model_id, purchase_no=purchase_no or ""
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = import_refmap_bytes(
        db,
        content,
        file.filename or "refmap.pdf",
        internal_code=ic,
        model_code=model_code.strip(),
        bom_model_id=bom_model_id,
        purchase_no=pn,
    )
    if result.get("status") == "success":
        _push_review_after_import(
            db,
            principal=principal,
            bom_model_id=bom_model_id or result.get("bom_model_id"),
            internal_code=internal_code,
            model_code=model_code,
            note="已导入位号图，请审核",
        )
    db.commit()
    return RefmapImportResult(**result)


@router.post("/refmaps/{file_id}/reaudit")
def refmaps_reaudit(file_id: int, db: Session = Depends(get_db)):
    try:
        result = reaudit_refmap_file(db, file_id)
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/refmaps/{file_id}/preview")
def refmaps_preview(
    file_id: int,
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    try:
        png, _, _ = render_refmap_page_png(db, file_id, page=page)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"位号图渲染失败: {exc}") from exc
    return Response(content=png, media_type="image/png")


@router.get("/refmaps/{file_id}/content")
def refmaps_content(
    file_id: int,
    db: Session = Depends(get_db),
):
    try:
        path = get_refmap_pdf_path(db, file_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
    )


@router.delete("/refmaps/{file_id}")
def refmaps_delete(
    file_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    row = db.query(PcbRefmapFile).filter(PcbRefmapFile.id == file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="位号图不存在")
    delete_refmap_store_file(row.internal_code, row.model_code, row.id, row.file_name)
    delete_refmap_file(db, file_id)
    db.commit()
    return {"message": "已清除位号图"}


@router.get("/placements/meta", response_model=PlacementMetaOut)
def placements_meta(db: Session = Depends(get_db)):
    return PlacementMetaOut(**get_placement_meta(db))


@router.get("/placements", response_model=list[PlacementFileOut])
def placements_list(
    internal_code: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
):
    return list_placement_catalog(db, internal_code, keyword)


@router.get("/placements/{file_id}/lines", response_model=list[PlacementLineOut])
def placements_lines(
    file_id: int,
    keyword: str = "",
    db: Session = Depends(get_db),
):
    row = db.query(PcbPlacementFile).filter(PcbPlacementFile.id == file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="坐标文件不存在")
    return get_placement_lines(db, file_id, keyword)


@router.post("/placements/import", response_model=PlacementImportResult)
async def placements_import(
    file: UploadFile = File(...),
    internal_code: str = Form(...),
    model_code: str = Form(...),
    bom_model_id: Optional[int] = Form(None),
    purchase_no: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_eng_import(principal)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    from eng_asset_scope import resolve_purchase_no_for_import

    ic = internal_code.strip().upper()
    try:
        pn = resolve_purchase_no_for_import(
            db, internal_code=ic, bom_model_id=bom_model_id, purchase_no=purchase_no or ""
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = import_placement_bytes(
        db,
        content,
        file.filename or "placement.txt",
        internal_code=ic,
        model_code=model_code.strip(),
        bom_model_id=bom_model_id,
        purchase_no=pn,
    )
    if result.get("status") == "success":
        _push_review_after_import(
            db,
            principal=principal,
            bom_model_id=bom_model_id or result.get("bom_model_id"),
            internal_code=internal_code,
            model_code=model_code,
            note="已导入贴片坐标，请审核",
        )
    db.commit()
    return PlacementImportResult(**result)


@router.delete("/placements/{file_id}")
def placements_delete(
    file_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    row = db.query(PcbPlacementFile).filter(PcbPlacementFile.id == file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="坐标文件不存在")
    delete_placement_file(db, file_id)
    db.commit()
    return {"message": "已清除贴片坐标"}


@router.get("/gerbers/meta", response_model=GerberMetaOut)
def gerbers_meta(db: Session = Depends(get_db)):
    return GerberMetaOut(**get_gerber_meta(db))


@router.get("/gerbers", response_model=list[GerberPackageOut])
def gerbers_list(
    internal_code: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
):
    return list_gerber_catalog(db, internal_code, keyword)


@router.get("/gerbers/{package_id}/files", response_model=list[GerberFileOut])
def gerbers_files(package_id: int, db: Session = Depends(get_db)):
    row = db.query(PcbGerberPackage).filter(PcbGerberPackage.id == package_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Gerber 资料包不存在")
    return get_gerber_files(db, package_id)


@router.post("/gerbers/{package_id}/reaudit", response_model=GerberAuditOut)
def gerbers_reaudit(
    package_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        result = reaudit_gerber_package(db, package_id)
        db.commit()
        return GerberAuditOut(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/gerbers/import", response_model=GerberImportResult)
async def gerbers_import(
    file: UploadFile = File(...),
    internal_code: str = Form(...),
    model_code: str = Form(...),
    bom_model_id: Optional[int] = Form(None),
    purchase_no: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_eng_import(principal)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    from eng_asset_scope import resolve_purchase_no_for_import

    ic = internal_code.strip().upper()
    try:
        pn = resolve_purchase_no_for_import(
            db, internal_code=ic, bom_model_id=bom_model_id, purchase_no=purchase_no or ""
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = import_gerber_zip(
        db,
        content,
        file.filename or "gerber.zip",
        internal_code=ic,
        model_code=model_code.strip(),
        bom_model_id=bom_model_id,
        purchase_no=pn,
    )
    if result.get("status") == "success":
        _push_review_after_import(
            db,
            principal=principal,
            bom_model_id=bom_model_id or result.get("bom_model_id"),
            internal_code=internal_code,
            model_code=model_code,
            note="已导入 Gerber，请审核",
        )
    db.commit()
    return GerberImportResult(**result)


@router.delete("/gerbers/{package_id}/files", response_model=GerberAuditOut)
def gerbers_remove_file(
    package_id: int,
    name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        result = remove_gerber_file(db, package_id, name)
        db.commit()
        return GerberAuditOut(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/gerbers/{package_id}")
def gerbers_delete(
    package_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    row = db.query(PcbGerberPackage).filter(PcbGerberPackage.id == package_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Gerber 资料包不存在")
    delete_gerber_package(db, package_id)
    db.commit()
    return {"message": "已清除 Gerber 资料"}


@router.get("/substitutions/meta", response_model=SubstitutionMetaOut)
def substitution_meta(customer_id: str = "", db: Session = Depends(get_db)):
    from config import get_customer, get_substitution_file_path
    from pathlib import Path

    cid = (customer_id or "").strip()
    q = db.query(SubstitutionRule)
    if cid:
        q = q.filter(SubstitutionRule.customer_id == cid)
    count = q.count()
    latest_q = db.query(SubstitutionRule.synced_at)
    if cid:
        latest_q = latest_q.filter(SubstitutionRule.customer_id == cid)
    latest = latest_q.order_by(SubstitutionRule.id.desc()).first()
    cust = get_customer(cid) if cid else None
    # 旧文件路径仅作兼容展示（菲利斯迁入用），不再作为日常同步源
    path = Path(get_substitution_file_path()) if (not cid or cid == "feilisi") else None
    return SubstitutionMetaOut(
        customer_id=cid,
        customer_name=(cust or {}).get("name") or "",
        row_count=count,
        synced_at=latest[0] if latest else None,
        source_file=str(path) if path else "",
        source_accessible=bool(path and path.is_file()),
    )


@router.get("/substitutions/template.xlsx")
def substitution_template(customer_id: str = ""):
    cid = (customer_id or "").strip().lower()
    profile = "yonglian" if cid in ("yonglian", "a067") else "standard"
    content = build_template_xlsx(profile=profile)
    fname = (
        "yonglian_substitution_template.xlsx"
        if profile == "yonglian"
        else "substitution_template.xlsx"
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/yonglian-sub-sheets")
def yonglian_sub_sheets(keyword: str = "", db: Session = Depends(get_db)):
    from yonglian_sub_sheet import list_sheets

    return list_sheets(db, keyword=keyword)


@router.get("/yonglian-sub-sheets/{sheet_id}")
def yonglian_sub_sheet_detail(sheet_id: int, db: Session = Depends(get_db)):
    from yonglian_sub_sheet import get_sheet

    try:
        return get_sheet(db, sheet_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/yonglian-sub-sheets/{sheet_id}")
def yonglian_sub_sheet_delete(
    sheet_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    from yonglian_sub_sheet import delete_sheet

    try:
        delete_sheet(db, sheet_id)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success", "message": "已删除"}


@router.post("/yonglian-sub-sheets/parse-image")
async def yonglian_sub_sheet_parse_image(
    file: UploadFile = File(...),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    raise HTTPException(status_code=400, detail="已关闭图片导入，请使用永联替代料 XLSX 表格导入")


@router.post("/yonglian-sub-sheets/confirm")
def yonglian_sub_sheet_confirm(
    body: dict,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    from yonglian_sub_sheet import upsert_sheet

    try:
        result = upsert_sheet(
            db,
            header=body.get("header") or {},
            lines=body.get("lines") or [],
            source_type=str(body.get("source_type") or "image"),
            source_file=str(body.get("source_file") or ""),
            replace_rules=bool(body.get("replace_rules", True)),
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/yonglian-sub-sheets/import-exact-0320")
def yonglian_sub_sheet_import_exact_0320(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """将指定传图（01-202607-CG-0320）一字不差写入永联替代模块。"""
    _require_planner(principal)
    from yonglian_sub_sheet import seed_sheet_from_image_0320

    result = seed_sheet_from_image_0320(db, source_file="客户传图-01-202607-CG-0320")
    db.commit()
    return result


@router.post("/substitutions/parse-xlsx", response_model=SubstitutionParseOut)
async def substitution_parse_xlsx(
    file: UploadFile = File(...),
    customer_id: str = Form(""),
    principal: AuthPrincipal = Depends(require_system_auth),
    db: Session = Depends(get_db),
):
    _require_planner(principal)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    try:
        parsed = parse_xlsx_bytes_with_db(db, raw, customer_id=customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SubstitutionParseOut(
        rows=parsed.get("rows") or [],
        format=parsed.get("format") or "",
        message=parsed.get("message") or "",
    )


@router.post("/substitutions/parse-image", response_model=SubstitutionParseOut)
async def substitution_parse_image(
    files: list[UploadFile] = File(...),
    customer_id: str = Form(""),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    raise HTTPException(status_code=400, detail="已关闭图片导入替代料，请改用 XLSX 表格导入")


@router.post("/substitutions/import-confirm", response_model=SubstitutionImportResult)
def substitution_import_confirm(
    body: SubstitutionImportConfirmIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        result = confirm_import(
            db,
            customer_id=body.customer_id,
            rows=[r.model_dump() for r in body.rows],
            mode=body.mode,
            source_type=body.source_type or "xlsx",
            source_file=body.source_file or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return SubstitutionImportResult(**result)


@router.post("/substitutions/migrate-legacy", response_model=SubstitutionSyncResult)
def substitution_migrate_legacy(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """一次性：从旧全局文件迁入菲利斯规则（覆盖 feilisi）。"""
    _require_planner(principal)
    result = sync_substitution_rules(db, customer_id="feilisi", replace=True)
    reload_substitution_cache_from_db(db, "feilisi")
    db.commit()
    return SubstitutionSyncResult(**result)


@router.post("/substitutions/sync-now", response_model=SubstitutionSyncResult)
def substitution_sync_now(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_system_auth)):
    """兼容旧入口：等价于迁入菲利斯旧表。"""
    return substitution_migrate_legacy(db=db, principal=principal)


@router.get("/substitutions", response_model=list[SubstitutionRuleOut])
def list_substitutions(
    customer_id: str = "",
    keyword: str = "",
    parent_code: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    cid = (customer_id or "").strip()
    if not cid:
        return []
    q = (
        db.query(SubstitutionRule)
        .filter(SubstitutionRule.customer_id == cid)
        .order_by(SubstitutionRule.comp_code.asc(), SubstitutionRule.id.asc())
    )
    pc = (parent_code or "").strip()
    if pc:
        q = q.filter(SubstitutionRule.parent_code == pc)
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(
            (SubstitutionRule.comp_code.like(like))
            | (SubstitutionRule.sub_code.like(like))
            | (SubstitutionRule.parent_code.like(like))
            | (SubstitutionRule.comp_name.like(like))
            | (SubstitutionRule.sub_name.like(like))
        )
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return rows


@router.post("/substitutions", response_model=SubstitutionRuleOut)
def create_substitution(
    body: SubstitutionRuleCreateIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        row = create_rule(db, body.customer_id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return row


@router.put("/substitutions/{rule_id}", response_model=SubstitutionRuleOut)
def update_substitution(
    rule_id: int,
    body: SubstitutionRuleUpdateIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        row = update_rule(db, rule_id, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return row


@router.delete("/substitutions/{rule_id}")
def delete_substitution(
    rule_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        delete_rule(db, rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"message": "已删除"}


@router.get("/models/{model_id}/process-map", response_model=ProcessMapOut)
def model_process_map(model_id: int, db: Session = Depends(get_db)):
    try:
        return get_model_process_map(db, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/models", response_model=list[BomModelListOut])
def list_models(
    internal_code: str = "",
    customer_id: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
):
    rows = list_bom_order_catalog(db, internal_code, customer_id, keyword)
    return [BomModelListOut(**row) for row in rows]


@router.post("/models/import", response_model=BomImportResult)
async def models_import(
    file: UploadFile = File(...),
    internal_code: str = Form(...),
    purchase_no: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_eng_import(principal)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    pn = (purchase_no or "").strip()
    if not pn:
        raise HTTPException(
            status_code=400,
            detail="请先在左侧点选在制订单（含订单号），再导入该订单 BOM",
        )
    ic = internal_code.strip().upper()
    if ic == "A120":
        raise HTTPException(
            status_code=400,
            detail="亿兰科请点「导入 BOM」：纯插件/纯贴片选 1 份；SMT+DIP 一次选 2 份 Excel",
        )
    result = import_bom_bytes(
        db,
        content,
        file.filename or "bom.xlsx",
        internal_code=ic,
        purchase_no=pn,
    )
    if result.get("status") == "success":
        bom_id = int(result.get("bom_model_id") or 0)
        if bom_id:
            bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
            if bom:
                bind_orders_to_bom_by_purchase_no(
                    db,
                    customer_id=bom.customer_id,
                    purchase_no=pn,
                    bom_model_id=bom.id,
                    model_code=bom.model_code,
                )
        try:
            relink_asset_records(db)
        except OSError as exc:
            logger.warning("导入后资料回链跳过: %s", exc)
        _push_review_after_import(
            db,
            principal=principal,
            bom_model_id=bom_id,
            note="已导入 BOM，请审核贴装与资料",
        )
    db.commit()
    if result.get("status") != "success":
        return BomImportResult(
            status="failed",
            message=result.get("message") or "导入失败",
            model_code=result.get("model_code") or "",
            lines=result.get("lines") or 0,
            bom_model_id=result.get("bom_model_id") or 0,
            internal_code=result.get("internal_code") or ic,
            purchase_no=pn,
            file=result.get("file") or "",
        )
    created = result.get("_created", 0)
    action = "新增" if created else "更新"
    return BomImportResult(
        status="success",
        message=f"{action} BOM {result.get('model_code')}（订单 {pn}），共 {result.get('lines')} 行，已推送审核",
        model_code=result.get("model_code") or "",
        lines=result.get("lines") or 0,
        bom_model_id=result.get("bom_model_id") or 0,
        internal_code=result.get("internal_code") or "",
        purchase_no=pn,
        file=result.get("file") or "",
    )


@router.post("/models/import-yilanke", response_model=BomImportResult)
async def models_import_yilanke(
    file_smt: UploadFile = File(..., description="第一份 BOM（单份时即本文件；双份时 SMT/DIP 均可）"),
    file_dip: Optional[UploadFile] = File(None, description="第二份 BOM（纯插件/纯贴片可省略）"),
    internal_code: str = Form("A120"),
    purchase_no: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """亿兰科：1 份（纯 DIP/纯 SMT）或 2 份（SMT+DIP 合并）导入。"""
    _require_eng_import(principal)
    pn = (purchase_no or "").strip()
    if not pn:
        raise HTTPException(
            status_code=400,
            detail="请先在左侧点选在制订单（含订单号），再导入该订单 BOM",
        )
    ic = (internal_code or "A120").strip().upper() or "A120"
    smt_bytes = await file_smt.read()
    dip_bytes = await file_dip.read() if file_dip is not None else b""
    if not smt_bytes:
        raise HTTPException(status_code=400, detail="请上传 BOM Excel")
    from yilanke_bom import import_yilanke_pair_bytes

    try:
        result = import_yilanke_pair_bytes(
            db,
            smt_content=smt_bytes,
            smt_filename=file_smt.filename or "bom.xlsx",
            dip_content=dip_bytes or None,
            dip_filename=(file_dip.filename if file_dip else "") or "dip.xlsx",
            internal_code=ic,
            purchase_no=pn,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("status") == "success":
        bom_id = int(result.get("bom_model_id") or 0)
        if bom_id:
            bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
            if bom:
                bind_orders_to_bom_by_purchase_no(
                    db,
                    customer_id=bom.customer_id,
                    purchase_no=pn,
                    bom_model_id=bom.id,
                    model_code=bom.model_code,
                )
        try:
            relink_asset_records(db)
        except OSError as exc:
            logger.warning("导入后资料回链跳过: %s", exc)
        note = (
            "已导入亿兰科单份 BOM，请审核贴装与资料"
            if result.get("single_file")
            else "已导入亿兰科 SMT+DIP 合并 BOM，请审核贴装与资料"
        )
        _push_review_after_import(
            db,
            principal=principal,
            bom_model_id=bom_id,
            note=note,
        )
    db.commit()
    if result.get("status") != "success":
        return BomImportResult(
            status="failed",
            message=result.get("message") or "导入失败",
            model_code=result.get("model_code") or "",
            lines=result.get("lines") or 0,
            bom_model_id=result.get("bom_model_id") or 0,
            internal_code=result.get("internal_code") or ic,
            purchase_no=pn,
            file=result.get("file") or "",
        )
    created = result.get("_created", 0)
    action = "新增" if created else "更新"
    smt_n = result.get("smt_lines") or 0
    dip_n = result.get("dip_lines") or 0
    if result.get("single_file"):
        kind = "纯 DIP" if dip_n >= smt_n else "纯 SMT"
        msg = (
            f"{action} BOM {result.get('model_code')}（订单 {pn}），"
            f"{kind} {result.get('lines')} 行，已推送审核"
        )
    else:
        msg = (
            f"{action} BOM {result.get('model_code')}（订单 {pn}），"
            f"合并 SMT {smt_n} + DIP {dip_n} = {result.get('lines')} 行，已推送审核"
        )
    return BomImportResult(
        status="success",
        message=msg,
        model_code=result.get("model_code") or "",
        lines=result.get("lines") or 0,
        bom_model_id=result.get("bom_model_id") or 0,
        internal_code=result.get("internal_code") or "",
        purchase_no=pn,
        file=result.get("file") or "",
    )


@router.delete("/models/{model_id}")
def models_clear(
    model_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """清除已导入 BOM，可重新导入正确文件。"""
    _require_eng_import(principal)
    try:
        result = clear_bom_model(db, model_id)
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/models/{model_id}/export")
def export_model_bom(model_id: int, db: Session = Depends(get_db)):
    bom = db.query(BomModel).filter(BomModel.id == model_id, BomModel.is_active.is_(True)).first()
    if not bom:
        raise HTTPException(status_code=404, detail="机型不存在")
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == model_id)
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    placement_index = load_placement_index(db, bom)
    from material_mount_service import load_mount_overrides

    profile_info, mounts = classify_lines_mount(
        lines,
        placement_index=placement_index,
        profile_override=bom.mount_profile_override,
        master_overrides=load_mount_overrides(db, internal_code=bom.internal_code or ""),
        internal_code=bom.internal_code or "",
    )
    line_rows = []
    for line, mount in zip(lines, mounts):
        line_rows.append({
            "seq": line.seq,
            "material_code": line.material_code,
            "material_name": line.material_name,
            "mount_type": mount["mount_type"],
            "mount_side": mount["mount_side"],
            "spec": line.spec,
            "qty_per": line.qty_per,
            "unit": line.unit,
            "position": line.position,
            "process": line.process,
            "remark": line.remark,
        })
    bom_dict = {
        "internal_code": bom.internal_code,
        "customer_id": bom.customer_id,
        "customer_name": bom.customer_name,
        "model_code": bom.model_code,
        "model_name": bom.model_name,
        "model_spec": bom.model_spec,
        "line_count": bom.line_count,
    }
    content = build_bom_xlsx(bom_dict, line_rows, profile_info=profile_info)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": bom_export_content_disposition(bom.model_code)},
    )


@router.get("/models/{model_id}", response_model=BomModelOut)
def get_model(model_id: int, db: Session = Depends(get_db)):
    row = db.query(BomModel).filter(BomModel.id == model_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="机型不存在")
    return row


@router.get("/models/{model_id}/lines", response_model=BomModelLinesOut)
def list_model_lines(model_id: int, db: Session = Depends(get_db)):
    bom = db.query(BomModel).filter(BomModel.id == model_id).first()
    if not bom:
        raise HTTPException(status_code=404, detail="机型不存在")
    lines = (
        db.query(BomLine)
        .filter(BomLine.bom_model_id == model_id)
        .order_by(BomLine.sort_order.asc(), BomLine.id.asc())
        .all()
    )
    placement_index = load_placement_index(db, bom)
    from material_mount_service import load_mount_overrides

    profile_info, mounts = classify_lines_mount(
        lines,
        placement_index=placement_index,
        profile_override=bom.mount_profile_override,
        master_overrides=load_mount_overrides(db, internal_code=bom.internal_code or ""),
        internal_code=bom.internal_code or "",
    )
    return BomModelLinesOut(
        mount_profile_override=bom.mount_profile_override or "",
        detected_profile=str(profile_info.get("profile") or "unknown"),
        profile_confidence=str(profile_info.get("confidence") or ""),
        profile_source=str(profile_info.get("source") or "auto"),
        lines=[_bom_line_out(line, mount) for line, mount in zip(lines, mounts)],
        unresolved_mount_count=sum(1 for m in mounts if not m.get("mount_type")),
        eng_review_status=bom.eng_review_status or "",
        eng_review_message=bom.eng_review_message,
    )


@router.put("/models/{model_id}/mount-profile", response_model=BomModelOut)
def set_model_mount_profile(
    model_id: int,
    body: BomModelMountProfileIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_eng_audit(principal)
    try:
        row = update_bom_mount_profile(db, model_id, body.mount_profile_override)
        from eng_review_service import reopen_bom_review_after_edit

        reopen_bom_review_after_edit(
            db,
            model_id,
            editor=principal.display_name or principal.username,
            note="贴装画像已修改，请重新审核通过",
        )
        db.commit()
        db.refresh(row)
        return row
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/review-inbox", response_model=list[EngReviewInboxOut])
def get_review_inbox(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    if not principal.can_eng_view:
        raise HTTPException(status_code=403, detail="无权限")
    from eng_review_service import list_review_inbox

    items = list_review_inbox(db, unread_only=unread_only)
    return items


@router.get("/review-pending")
def get_review_pending(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """兼容旧接口：仅管理员返回待审清单。"""
    from eng_review_service import my_todos_for_principal

    payload = my_todos_for_principal(db, role=principal.role, username=principal.username)
    if payload.get("todo_kind") != "review":
        raise HTTPException(status_code=403, detail="无审核待办权限")
    return payload.get("items") or []


@router.get("/todos")
def get_my_todos(
    internal_code: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """按当前登录帐号返回各自待处理事项（待审核 / 待导入 / 审核退回）。"""
    from eng_review_service import my_todos_for_principal

    return my_todos_for_principal(
        db,
        role=principal.role,
        username=principal.username,
        internal_code=internal_code,
    )


@router.post("/todos/{inbox_id}/ack")
def ack_todo_inbox(
    inbox_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """资料员打开退回待办后标记已处理（从待办列表移除）。"""
    from eng_review_service import mark_rejected_inbox_done

    n = mark_rejected_inbox_done(db, inbox_id=inbox_id)
    db.commit()
    return {"message": "已确认", "updated": n}


@router.get("/review-inbox/count")
def get_review_inbox_count(
    internal_code: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """顶栏角标数量：按帐号角色返回各自待办数。"""
    from eng_review_service import my_todos_for_principal

    payload = my_todos_for_principal(
        db,
        role=principal.role,
        username=principal.username,
        internal_code=internal_code,
    )
    n = int(payload.get("count") or 0)
    return {
        "unread": n,
        "pending": n,
        "todo_kind": payload.get("todo_kind") or "",
        "title": payload.get("title") or "待处理事项",
        "internal_code": (internal_code or "").strip().upper(),
    }


@router.get("/models/{model_id}/review-dossier")
def get_model_review_dossier(
    model_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """审核工作台档案：订单信息 + 资料齐套检查 + 流程步骤。"""
    if not principal.can_eng_view:
        raise HTTPException(status_code=403, detail="无权限")
    from eng_review_service import build_review_dossier

    try:
        return build_review_dossier(db, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/models/{model_id}/same-bom-peers")
def get_same_bom_peers(
    model_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """同 BOM 版本（内容指纹相同）的其它订单，用于同步坐标/Gerber。"""
    if not principal.can_eng_view:
        raise HTTPException(status_code=403, detail="无权限")
    from eng_asset_scope import list_same_bom_peers

    return {"peers": list_same_bom_peers(db, model_id)}


@router.post("/models/{model_id}/sync-assets")
def sync_model_assets_from_peer(
    model_id: int,
    source_bom_model_id: int = Form(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """从同 BOM 版本的源订单同步坐标 / Gerber / 位号图到本订单。"""
    _require_eng_import(principal)
    from eng_asset_scope import sync_assets_from_peer

    try:
        result = sync_assets_from_peer(
            db, target_bom_id=model_id, source_bom_id=source_bom_model_id
        )
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/models/{model_id}/review/approve")
def review_approve(
    model_id: int,
    body: EngReviewActionIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_eng_audit(principal)
    from eng_review_service import approve_bom_review

    try:
        row = approve_bom_review(
            db, model_id, reviewer=_submitter_name(principal), message=body.message or "审核通过"
        )
        db.commit()
        return {
            "message": "已审核通过",
            "bom_model_id": row.id,
            "eng_review_status": row.eng_review_status,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/models/{model_id}/review/reject")
def review_reject(
    model_id: int,
    body: EngReviewActionIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_eng_audit(principal)
    from eng_review_service import reject_bom_review

    try:
        row = reject_bom_review(
            db, model_id, reviewer=_submitter_name(principal), message=body.message
        )
        db.commit()
        return {
            "message": "已退回",
            "bom_model_id": row.id,
            "eng_review_status": row.eng_review_status,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/models/{model_id}/unresolved-mount", response_model=list[UnresolvedMountLineOut])
def get_unresolved_mount(model_id: int, db: Session = Depends(get_db)):
    from material_mount_service import list_unresolved_mount_lines

    try:
        return list_unresolved_mount_lines(db, model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/models/{model_id}/mount-readiness", response_model=MountReadinessOut)
def get_mount_readiness(model_id: int, db: Session = Depends(get_db)):
    """工序·面别完备性：仅检查 BOM+坐标是否足以精确分工序/分面。"""
    from mount_readiness import check_mount_readiness

    try:
        result = check_mount_readiness(db, model_id)
        db.commit()
        return MountReadinessOut(**result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/mount-profiles", response_model=MaterialMountProfileOut)
def put_mount_profile(
    body: MaterialMountProfileIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """确认物料贴装类型，写入主数据后全局生效。"""
    _require_eng_audit(principal)
    from material_mount_service import upsert_mount_profile

    try:
        row = upsert_mount_profile(
            db,
            body.material_code,
            body.mount_type,
            mount_side=body.mount_side or "",
            material_name=body.material_name,
            updated_by=principal.display_name or principal.username,
            internal_code=body.internal_code or "",
        )
        if body.bom_model_id:
            from eng_review_service import reopen_bom_review_after_edit

            reopen_bom_review_after_edit(
                db,
                int(body.bom_model_id),
                editor=principal.display_name or principal.username,
                note=f"贴装/面别已修正（{body.material_code}），请重新审核通过",
            )
        db.commit()
        db.refresh(row)
        return row
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/lines/{line_id}", response_model=BomLineOut)
def edit_line(
    line_id: int,
    body: BomLineUpdateIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        row = update_bom_line(db, line_id, body.model_dump(exclude_unset=True))
        bom = db.query(BomModel).filter(BomModel.id == row.bom_model_id).first()
        if not bom:
            raise HTTPException(status_code=404, detail="机型不存在")
        mount = mount_for_line(db, bom, row)
        db.commit()
        return _bom_line_out(row, mount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/orders/{line_key}/bind-bom")
def bind_bom(
    line_key: str,
    body: OrderBindBomIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    try:
        bind_order_bom(db, line_key, body.bom_model_id)
        db.commit()
        return {"message": "绑定成功"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/orders/auto-bind")
def auto_bind(
    customer_id: str = "",
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_planner(principal)
    count = auto_bind_orders(db, customer_id or None)
    db.commit()
    return {"message": f"已自动绑定 {count} 条订单", "bound_count": count}


@router.post("/orders/delete")
def orders_delete(
    body: EngOrderDeleteIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """从工程资料删除订单（需密码）。清 BOM/待审/订单级资产并隐藏目录行；不删 SRM 在制单。"""
    _require_eng_import(principal)
    _require_order_delete_password(body.password)
    try:
        result = delete_engineering_order(
            db,
            internal_code=body.internal_code or "",
            purchase_no=body.purchase_no or "",
            model_code=body.model_code or "",
            bom_model_id=body.bom_model_id,
            hidden_by=_submitter_name(principal),
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orders/{line_key}/kitting", response_model=KittingOut)
def get_order_kitting(line_key: str, db: Session = Depends(get_db)):
    try:
        result = order_kitting(db, line_key)
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/kitting", response_model=KittingOut)
def get_model_kitting(
    bom_model_id: int = Query(..., ge=1),
    order_qty: float = Query(1, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return compute_kitting(db, bom_model_id, order_qty)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/kitting/export")
def export_model_kitting(
    bom_model_id: int = Query(..., ge=1),
    order_qty: float = Query(1, ge=0),
    db: Session = Depends(get_db),
):
    try:
        kit = compute_kitting(db, bom_model_id, order_qty)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    content = build_kitting_xlsx(kit)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": kitting_export_content_disposition(kit.get("model_code") or "", order_qty)},
    )


@router.get("/orders/{line_key}/kitting/export")
def export_order_kitting(line_key: str, db: Session = Depends(get_db)):
    try:
        kit = order_kitting(db, line_key)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not kit.get("lines"):
        raise HTTPException(status_code=400, detail=kit.get("message") or "无可导出的齐套明细")
    content = build_kitting_xlsx(kit)
    model_code = kit.get("model_code") or kit.get("product_goods_no") or "order"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": kitting_export_content_disposition(model_code, kit.get("order_qty") or 0)},
    )
