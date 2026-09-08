"""品质管理 API（独立于产线扫码）。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from barcode_trace_service import (
    batch_trace_barcodes,
    batch_trace_summary,
    lookup_barcode_trace,
    search_batch_trace_options,
)
from complaint_service import (
    dashboard_stats as complaint_dashboard_stats,
    filter_meta as complaint_filter_meta,
    get_image_file as complaint_get_image_file,
    import_complaint_excel,
    list_batches as complaint_list_batches,
    list_details as complaint_list_details,
)
from database import get_db
from process_defect_service import (
    dashboard_stats,
    filter_meta,
    import_defect_excel,
    list_defect_details,
    list_import_batches,
)
from quality_service import list_aoi_fails, list_overrides, lookup_aoi, override_aoi_to_pass
from pre_oven_aoi_qc_service import (
    list_pending_repairs,
    list_qc_records,
    override_to_pass as pre_oven_override_to_pass,
)
from system_auth import AuthPrincipal, require_quality

router = APIRouter(
    prefix="/api/quality",
    tags=["quality"],
    dependencies=[Depends(require_quality)],
)


class OverridePassIn(BaseModel):
    barcode: str = Field(..., min_length=4, max_length=64)
    reason: str = Field(..., min_length=2, max_length=256)
    remark: str = Field("", max_length=512)
    confirm_password: str = Field(..., min_length=1, max_length=64)


@router.get("/aoi/fails")
def api_aoi_fails(
    keyword: Optional[str] = Query(None, max_length=64),
    purchase_no: Optional[str] = Query(None, max_length=64),
    model_code: Optional[str] = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return list_aoi_fails(
        db,
        keyword=keyword or "",
        purchase_no=purchase_no or "",
        model_code=model_code or "",
        limit=limit,
        offset=offset,
    )


@router.get("/aoi/lookup")
def api_aoi_lookup(
    barcode: str = Query(..., min_length=4, max_length=64),
    db: Session = Depends(get_db),
):
    try:
        return lookup_aoi(db, barcode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/aoi/override-pass")
def api_aoi_override_pass(
    body: OverridePassIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quality),
):
    try:
        out = override_aoi_to_pass(
            db,
            barcode=body.barcode,
            confirm_password=body.confirm_password,
            submitted_by=principal.username or str(principal.user_id),
            reason=body.reason,
            remark=body.remark or "",
        )
        db.commit()
        return out
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise


@router.get("/aoi/overrides")
def api_aoi_overrides(
    barcode: Optional[str] = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return list_overrides(db, barcode=barcode or "", limit=limit, offset=offset)


@router.get("/pre-oven-aoi/fails")
def api_pre_oven_aoi_fails(
    keyword: Optional[str] = Query(None, max_length=64),
    purchase_no: Optional[str] = Query(None, max_length=64),
    model_code: Optional[str] = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return list_pending_repairs(
        db,
        keyword=keyword or "",
        purchase_no=purchase_no or "",
        model_code=model_code or "",
        limit=limit,
        offset=offset,
    )


@router.post("/pre-oven-aoi/override-pass")
def api_pre_oven_aoi_override_pass(
    body: OverridePassIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quality),
):
    try:
        out = pre_oven_override_to_pass(
            db,
            barcode=body.barcode,
            confirm_password=body.confirm_password,
            submitted_by=principal.username or str(principal.user_id),
            reason=body.reason,
            remark=body.remark or "",
        )
        db.commit()
        return out
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise


@router.get("/pre-oven-aoi/records")
def api_pre_oven_aoi_records(
    barcode: Optional[str] = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return list_qc_records(db, barcode=barcode or "", limit=limit, offset=offset)


@router.post("/process-defects/import")
async def api_process_defect_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quality),
):
    name = (file.filename or "").strip()
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 不良记录表")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        out = import_defect_excel(
            db,
            data=data,
            filename=name,
            operator=principal.username or str(principal.user_id),
        )
        db.commit()
        return out
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise


@router.get("/process-defects/batches")
def api_process_defect_batches(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return {"items": list_import_batches(db, limit=limit)}


@router.get("/process-defects/meta")
def api_process_defect_meta(db: Session = Depends(get_db)):
    return filter_meta(db)


@router.get("/process-defects/dashboard")
def api_process_defect_dashboard(
    year_month: Optional[str] = Query(None, max_length=7),
    customer: Optional[str] = Query(None, max_length=64),
    station: Optional[str] = Query(None, max_length=32),
    model_code: Optional[str] = Query(None, max_length=128),
    db: Session = Depends(get_db),
):
    return dashboard_stats(
        db,
        year_month=year_month or "",
        customer=customer or "",
        station=station or "",
        model_code=model_code or "",
    )


@router.get("/process-defects/details")
def api_process_defect_details(
    year_month: Optional[str] = Query(None, max_length=7),
    customer: Optional[str] = Query(None, max_length=64),
    station: Optional[str] = Query(None, max_length=32),
    model_code: Optional[str] = Query(None, max_length=128),
    phenomenon: Optional[str] = Query(None, max_length=128),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return list_defect_details(
        db,
        year_month=year_month or "",
        customer=customer or "",
        station=station or "",
        model_code=model_code or "",
        phenomenon=phenomenon or "",
        limit=limit,
        offset=offset,
    )


@router.post("/complaints/import")
async def api_complaint_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_quality),
):
    name = (file.filename or "").strip()
    if not name.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 客诉记录表")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        out = import_complaint_excel(
            db,
            data=data,
            filename=name,
            operator=principal.username or str(principal.user_id),
        )
        db.commit()
        return out
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise


@router.get("/complaints/batches")
def api_complaint_batches(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return {"items": complaint_list_batches(db, limit=limit)}


@router.get("/complaints/meta")
def api_complaint_meta(db: Session = Depends(get_db)):
    return complaint_filter_meta(db)


@router.get("/complaints/dashboard")
def api_complaint_dashboard(
    year_month: Optional[str] = Query(None, max_length=7),
    customer: Optional[str] = Query(None, max_length=64),
    station: Optional[str] = Query(None, max_length=64),
    dept: Optional[str] = Query(None, max_length=64),
    model_code: Optional[str] = Query(None, max_length=128),
    db: Session = Depends(get_db),
):
    return complaint_dashboard_stats(
        db,
        year_month=year_month or "",
        customer=customer or "",
        station=station or "",
        dept=dept or "",
        model_code=model_code or "",
    )


@router.get("/complaints/details")
def api_complaint_details(
    year_month: Optional[str] = Query(None, max_length=7),
    customer: Optional[str] = Query(None, max_length=64),
    station: Optional[str] = Query(None, max_length=64),
    dept: Optional[str] = Query(None, max_length=64),
    model_code: Optional[str] = Query(None, max_length=128),
    phenomenon: Optional[str] = Query(None, max_length=128),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return complaint_list_details(
        db,
        year_month=year_month or "",
        customer=customer or "",
        station=station or "",
        dept=dept or "",
        model_code=model_code or "",
        phenomenon=phenomenon or "",
        limit=limit,
        offset=offset,
    )


@router.get("/complaints/images/{image_id}")
def api_complaint_image(image_id: int, db: Session = Depends(get_db)):
    try:
        path, content_type = complaint_get_image_file(db, image_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, media_type=content_type)


@router.get("/barcode-trace")
def api_barcode_trace(
    barcode: str = Query(..., min_length=4, max_length=128),
    db: Session = Depends(get_db),
):
    """只读：本系统入库 + 旧站包装，不影响生产扫码。"""
    return lookup_barcode_trace(db, barcode)


@router.get("/barcode-trace/options")
def api_barcode_trace_options(
    keyword: str = Query(..., min_length=2, max_length=128),
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """订单/机型候选列表（只读）。"""
    return search_batch_trace_options(db, keyword, limit=limit)


@router.get("/barcode-trace/batch-summary")
def api_barcode_trace_batch_summary(
    purchase_no: str = Query(..., min_length=1, max_length=128),
    model_code: str = Query("", max_length=128),
    db: Session = Depends(get_db),
):
    """选定订单+机型后的分站汇总（只读）。"""
    try:
        return batch_trace_summary(db, purchase_no, model_code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/barcode-trace/batch-barcodes")
def api_barcode_trace_batch_barcodes(
    purchase_no: str = Query(..., min_length=1, max_length=128),
    model_code: str = Query("", max_length=128),
    station: str = Query(..., min_length=1, max_length=32),
    scope: str = Query("passed", max_length=16),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """分站已过/未过条码分页（只读）。"""
    try:
        return batch_trace_barcodes(
            db,
            purchase_no=purchase_no,
            model_code=model_code,
            station=station,
            scope=scope,
            page=page,
            page_size=page_size,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---------- DIP 首件（品质查询） ----------


@router.get("/dip-first-article/sessions")
def api_quality_dip_fai_list(
    keyword: Optional[str] = Query(None, max_length=128),
    status: Optional[str] = Query(None, max_length=24),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    from dip_first_article_service import list_sessions

    return list_sessions(
        db,
        keyword=keyword or "",
        status=status or "",
        limit=limit,
        offset=offset,
    )


@router.get("/dip-first-article/sessions/{session_id}")
def api_quality_dip_fai_detail(
    session_id: int,
    db: Session = Depends(get_db),
):
    from dip_first_article_service import get_session

    try:
        return get_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/dip-first-article/sessions/{session_id}/board-image")
def api_quality_dip_fai_board_image(
    session_id: int,
    db: Session = Depends(get_db),
):
    from dip_first_article_service import resolve_image_path
    from models import DipFirstArticleSession

    sess = db.query(DipFirstArticleSession).filter(DipFirstArticleSession.id == session_id).first()
    if not sess or not sess.board_image_rel:
        raise HTTPException(status_code=404, detail="无首件总图")
    try:
        path = resolve_image_path(sess.board_image_rel)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, media_type=sess.board_image_content_type or "image/jpeg")


@router.get("/dip-first-article/lines/{line_id}/image")
def api_quality_dip_fai_line_image(
    line_id: int,
    db: Session = Depends(get_db),
):
    from dip_first_article_service import resolve_image_path
    from models import DipFirstArticleLine

    line = db.query(DipFirstArticleLine).filter(DipFirstArticleLine.id == line_id).first()
    if not line or not line.material_image_rel:
        raise HTTPException(status_code=404, detail="无物料核对图")
    try:
        path = resolve_image_path(line.material_image_rel)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/dip-first-article/sessions/{session_id}")
def api_quality_dip_fai_delete(
    session_id: int,
    db: Session = Depends(get_db),
):
    from dip_first_article_service import delete_session

    try:
        return delete_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---------- SMT 巡检查料（品质查询） ----------


@router.get("/smt-ipqc/sessions")
def api_quality_smt_ipqc_list(
    keyword: Optional[str] = Query(None, max_length=128),
    status: Optional[str] = Query(None, max_length=24),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    from smt_ipqc_service import list_sessions

    return list_sessions(
        db,
        keyword=keyword or "",
        status=status or "",
        limit=limit,
        offset=offset,
    )


@router.get("/smt-ipqc/sessions/{session_id}")
def api_quality_smt_ipqc_detail(
    session_id: int,
    db: Session = Depends(get_db),
):
    from smt_ipqc_service import get_session

    try:
        return get_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/smt-ipqc/lines/{line_id}/image")
def api_quality_smt_ipqc_line_image(
    line_id: int,
    db: Session = Depends(get_db),
):
    from models import SmtIpqcLine
    from smt_ipqc_service import resolve_image_path

    line = db.query(SmtIpqcLine).filter(SmtIpqcLine.id == line_id).first()
    if not line or not line.material_image_rel:
        raise HTTPException(status_code=404, detail="无物料核对图")
    try:
        path = resolve_image_path(line.material_image_rel)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/smt-ipqc/sessions/{session_id}")
def api_quality_smt_ipqc_delete(
    session_id: int,
    db: Session = Depends(get_db),
):
    from smt_ipqc_service import delete_session

    try:
        return delete_session(db, session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
