"""镭雕登记 + AOI 同步 + 订单板码查询"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from aoi_sync import sync_aoi_from_share
from database import get_db
from enjiu_ats_sync import sync_enjiu_ats_from_shares
from ict_sync import boards_for_ict_purchase, rematch_ict_to_laser, sync_ict_from_shares
from laser_service import (
    boards_for_purchase,
    create_laser_batches,
    delete_laser_batch,
    import_enjiu_print_barcode_register,
    import_feilisi_print_barcode_register,
    import_laser_excel,
    list_laser_batches,
    rematch_aoi_to_laser,
)
from tts_laser_sync import sync_laser_from_tts
from system_auth import AuthPrincipal, require_admin_or_planner, require_system_auth

router = APIRouter(
    prefix="/api/laser",
    tags=["laser"],
    dependencies=[Depends(require_system_auth)],
)


class LaserBatchIn(BaseModel):
    customer_id: str = "feilisi"
    customer_name: str = "菲利斯"
    laser_date: str = Field(..., description="YYMMDD，可多日用 \\ 分隔")
    model_code: str
    purchase_no: str
    order_qty: float = 0
    seq_range: str = Field(..., description="如 00001-03000")
    remark: Optional[str] = None


class LaserBatchOut(BaseModel):
    id: int
    customer_id: str
    customer_name: Optional[str] = None
    laser_date: str
    model_code: str
    purchase_no: str
    order_qty: float
    seq_from: int
    seq_to: int
    barcode_prefix: Optional[str] = None
    remark: Optional[str] = None
    source: str
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/batches", response_model=list[LaserBatchOut])
def api_list_batches(
    customer_id: str = "",
    purchase_no: str = "",
    model_code: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    return list_laser_batches(
        db,
        customer_id=customer_id,
        purchase_no=purchase_no,
        model_code=model_code,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.post("/batches", response_model=list[LaserBatchOut])
def api_create_batch(
    payload: LaserBatchIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    try:
        rows = create_laser_batches(db, payload.model_dump(), created_by=principal.username)
        db.commit()
        for r in rows:
            db.refresh(r)
        return rows
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/batches/{batch_id}")
def api_delete_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    try:
        delete_laser_batch(db, batch_id)
        db.commit()
        return {"ok": True}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/batches/import-excel")
async def api_import_excel(
    file: UploadFile = File(...),
    customer_id: str = Query("feilisi"),
    customer_name: str = Query("菲利斯"),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    raw = await file.read()
    tmp = Path(__file__).resolve().parent.parent / "data" / "uploads"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / (file.filename or "laser.xlsx")
    path.write_bytes(raw)
    try:
        result = import_laser_excel(
            db,
            path,
            customer_id=customer_id,
            customer_name=customer_name,
            created_by=principal.username,
        )
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/batches/import-default")
def api_import_default_excel(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    from config import get_laser_import_default_path

    path = Path(get_laser_import_default_path())
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"未找到文件：{path}")
    try:
        result = import_laser_excel(
            db,
            path,
            customer_id="feilisi",
            customer_name="菲利斯",
            created_by=principal.username,
        )
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/batches/import-feilisi-print-register")
def api_import_feilisi_print_register(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    """从共享盘 I-表格类/打印条码登记表 导入「菲利斯」贴码/打印流水绑定。"""
    try:
        result = import_feilisi_print_barcode_register(db, created_by=principal.username)
        total_ict = 0
        total_aoi = 0
        offset = 0
        for _ in range(80):
            rematch = rematch_ict_to_laser(db, limit=5000, offset=offset)
            linked = int(rematch.get("linked") or 0)
            scanned = int(rematch.get("scanned") or 0)
            total_ict += linked
            if scanned == 0:
                break
            if linked == 0:
                offset += scanned
            else:
                offset = 0
        aoi = rematch_aoi_to_laser(db)
        total_aoi = int(aoi.get("matched") or 0)
        db.commit()
        result["ict_rematch_linked"] = total_ict
        result["aoi_rematch_matched"] = total_aoi
        return result
    except FileNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/batches/import-enjiu-print-register")
def api_import_enjiu_print_register(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    """从共享盘 I-表格类/打印条码登记表 导入「恩玖-鼎雄」贴码流水绑定。"""
    try:
        result = import_enjiu_print_barcode_register(db, created_by=principal.username)
        # 导入后立刻把库内未归属的 ICT 恩玖条码挂上订单
        total_linked = 0
        offset = 0
        for _ in range(80):
            rematch = rematch_ict_to_laser(db, limit=5000, offset=offset)
            linked = int(rematch.get("linked") or 0)
            scanned = int(rematch.get("scanned") or 0)
            total_linked += linked
            if scanned == 0:
                break
            if linked == 0:
                offset += scanned
            else:
                offset = 0
        db.commit()
        result["ict_rematch_linked"] = total_linked
        return result
    except FileNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/aoi/sync")
def api_aoi_sync(
    force_all: bool = False,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    try:
        result = sync_aoi_from_share(db, force_all=force_all)
        rematch = rematch_aoi_to_laser(db)
        db.commit()
        result["rematch"] = rematch
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/aoi/rematch")
def api_aoi_rematch(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    result = rematch_aoi_to_laser(db)
    db.commit()
    return result


@router.post("/ict/sync")
def api_ict_sync(
    force_all: bool = False,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    try:
        result = sync_ict_from_shares(db, force_all=force_all)
        # 恩玖 ATS（192.168.2.156 Var_Type）一并拉取，写入同一 ICT 结果表
        try:
            ats = sync_enjiu_ats_from_shares(db, force_all=force_all)
            result["enjiu_ats"] = ats
        except Exception as e:
            result["enjiu_ats"] = {"status": "failed", "message": str(e)}
        rematch = rematch_ict_to_laser(db)
        db.commit()
        result["rematch"] = rematch
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/enjiu-ats/sync")
def api_enjiu_ats_sync(
    force_all: bool = False,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    """单独抓取恩玖 ATS：\\\\IP\\ENJOY\\ATS\\log\\Var_Type。"""
    try:
        result = sync_enjiu_ats_from_shares(db, force_all=force_all)
        rematch = rematch_ict_to_laser(db)
        db.commit()
        result["rematch"] = rematch
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/ict/rematch")
def api_ict_rematch(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    result = rematch_ict_to_laser(db)
    db.commit()
    return result


@router.get("/orders/{purchase_no}/ict-boards")
def api_order_ict_boards(
    purchase_no: str,
    customer_id: str = "",
    keyword: str = "",
    result: str = "",
    include_items: bool = Query(True),
    limit: int = Query(3000, ge=1, le=20000),
    db: Session = Depends(get_db),
):
    return boards_for_ict_purchase(
        db,
        purchase_no,
        customer_id=customer_id,
        keyword=keyword,
        result=result,
        include_items=include_items,
        limit=limit,
    )


@router.post("/tts/sync")
def api_tts_laser_sync(
    rematch: bool = True,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_admin_or_planner),
):
    """从菲利斯 TTS 拉取镭雕/补码流水段，写入镭雕登记并重挂 AOI。"""
    try:
        result = sync_laser_from_tts(
            db,
            rematch=rematch,
            created_by=principal.username or "tts",
        )
        db.commit()
        return result
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/orders/{purchase_no}/boards")
def api_order_boards(
    purchase_no: str,
    customer_id: str = "",
    keyword: str = "",
    result: str = "",
    include_items: bool = Query(True),
    limit: int = Query(3000, ge=1, le=20000),
    db: Session = Depends(get_db),
):
    return boards_for_purchase(
        db,
        purchase_no,
        customer_id=customer_id,
        keyword=keyword,
        result=result,
        include_items=include_items,
        limit=limit,
    )
