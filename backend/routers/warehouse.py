import json

from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from config import get_warehouse_share_path, load_config
from database import get_db
from models import ExcelImportLog, StockInRecord, StockIssue, StockLedger, StockReturn, WarehouseMaterial, WarehouseMovement, WarehouseSheetSnapshot, WarehouseWorkbookSnapshot
from schemas import (
    BatchInboundIn,
    BatchInboundLineIn,
    BatchInboundParseOut,
    BatchIssueIn,
    BatchIssueParseOut,
    BatchIssueImportLineOut,
    BatchOperationResultOut,
    ExcelImportResult,
    FinishedGoodsRowOut,
    OrderIssuePreviewOut,
    SheetSnapshotDataOut,
    SheetSnapshotMetaOut,
    StockInIn,
    StockInRecordOut,
    StockIssueIn,
    StockIssueOut,
    StockLedgerOut,
    StockReturnIn,
    StockReturnOut,
    WarehouseBomModelCandidateOut,
    WarehouseMaterialOut,
    WarehouseMaterialDetailOut,
    WarehouseModelMaterialLineOut,
    WarehouseModelMaterialsOut,
    WarehouseMovementOut,
    WarehouseOperationIn,
    WorkbookSnapshotOut,
)
from system_auth import AuthPrincipal, require_system_auth
from warehouse_excel import build_template_workbook, export_inventory_workbook, resolve_share_dir, sync_all_from_share
from warehouse_inbound_excel import build_inbound_template_workbook, parse_inbound_excel
from warehouse_issue_excel import build_issue_template_workbook, issue_template_filename, parse_issue_excel
from warehouse_batch import batch_inbound, batch_issue_order, get_order_issue_preview
from warehouse_material_detail import get_material_detail
from warehouse_movements import MOVEMENT_LABELS
from warehouse_operation import apply_movement
from warehouse_sync import sync_warehouse_materials
from warehouse_service import (
    INBOUND_SOURCE_LABELS,
    ISSUE_STATUS_PENDING,
    RETURN_STATUS_PENDING,
    confirm_issue,
    confirm_return,
    create_issue,
    create_return,
    get_material,
    reject_issue,
    reject_return,
    stock_in,
)
from substitution_service import resolve_group_stock
from engineering_service import normalize_code

router = APIRouter(prefix="/api/warehouse", tags=["warehouse"], dependencies=[Depends(require_system_auth)])


def _movement_out(row: WarehouseMovement) -> WarehouseMovementOut:
    return WarehouseMovementOut(
        id=row.id,
        customer_id=row.customer_id,
        customer_name=row.customer_name,
        movement_type=row.movement_type,
        movement_type_name=MOVEMENT_LABELS.get(row.movement_type, row.movement_type),
        material_code=row.material_code,
        material_name=row.material_name,
        spec=row.spec,
        unit=row.unit or "PCS",
        qty=row.qty,
        qty_delta=row.qty_delta,
        order_no=row.order_no or "",
        product_model=row.product_model or "",
        order_qty=row.order_qty,
        process=row.process,
        doc_date=row.doc_date or "",
        ref_no=row.ref_no or "",
        source=row.source,
        operator=row.operator,
        giver=getattr(row, "giver", None),
        receiver=getattr(row, "receiver", None),
        remark=row.remark,
        created_at=row.created_at,
    )


def _batch_result_out(result: dict) -> BatchOperationResultOut:
    return BatchOperationResultOut(
        ref_no=result["ref_no"],
        success_count=result["success_count"],
        movements=[_movement_out(m) for m in result.get("movements") or []],
        errors=result.get("errors") or [],
        skipped=result.get("skipped") or [],
        created_count=int(result.get("created_count") or 0),
        created_codes=list(result.get("created_codes") or []),
    )


def _customer_stock_map(db: Session, customer_id: str) -> dict[str, WarehouseMaterial]:
    rows = db.query(WarehouseMaterial).filter(WarehouseMaterial.customer_id == customer_id).all()
    return {normalize_code(row.material_code): row for row in rows}


def _material_out(
    row: WarehouseMaterial,
    last_in: Optional[StockInRecord] = None,
    stock_map: Optional[dict[str, WarehouseMaterial]] = None,
    last_op: Optional[StockLedger] = None,
) -> WarehouseMaterialOut:
    source_name = INBOUND_SOURCE_LABELS.get(last_in.source, last_in.source) if last_in else None
    if stock_map is None:
        stock_map = {normalize_code(row.material_code): row}
    stock_info = resolve_group_stock(row.material_code, stock_map, row.customer_id or "")
    own_available = max(row.qty - row.locked_qty, 0)
    op_type = last_op.movement_type if last_op else None
    op_labels = {
        "stock_in": "来料",
        "issue_out": "发料",
        "return_in": "退料",
        "excel_sync": "共享盘同步",
    }
    return WarehouseMaterialOut(
        id=row.id,
        customer_id=row.customer_id,
        customer_name=row.customer_name,
        material_code=row.material_code,
        material_name=row.material_name,
        spec=row.spec,
        unit=row.unit or "PCS",
        qty=row.qty,
        locked_qty=row.locked_qty,
        available_qty=own_available,
        group_available_qty=float(stock_info.get("group_available_qty") or own_available),
        stock_primary_code=str(stock_info.get("stock_primary_code") or row.material_code),
        substitute_codes=list(stock_info.get("substitute_codes") or []),
        is_substitute_alias=bool(stock_info.get("is_substitute_alias")),
        excel_count_qty=row.excel_count_qty,
        excel_in_qty=row.excel_in_qty,
        excel_demand_qty=row.excel_demand_qty,
        excel_synced_at=row.excel_synced_at,
        remark=row.remark,
        last_inbound_at=last_in.created_at if last_in else None,
        last_inbound_qty=last_in.qty if last_in else None,
        last_inbound_source=last_in.source if last_in else None,
        last_inbound_source_name=source_name,
        last_op_at=last_op.created_at if last_op else None,
        last_op_type=op_type,
        last_op_type_name=op_labels.get(op_type or "", op_type) if op_type else None,
        last_op_giver=getattr(last_op, "giver", None) if last_op else None,
        last_op_receiver=getattr(last_op, "receiver", None) if last_op else None,
        last_op_operator=last_op.operator if last_op else None,
    )


def _latest_inbound_map(db: Session, material_ids: list[int]) -> dict[int, StockInRecord]:
    if not material_ids:
        return {}
    rows = (
        db.query(StockInRecord)
        .filter(StockInRecord.material_id.in_(material_ids))
        .order_by(StockInRecord.created_at.desc())
        .all()
    )
    result: dict[int, StockInRecord] = {}
    for row in rows:
        if row.material_id not in result:
            result[row.material_id] = row
    return result


def _latest_ledger_map(db: Session, material_ids: list[int]) -> dict[int, StockLedger]:
    if not material_ids:
        return {}
    rows = (
        db.query(StockLedger)
        .filter(StockLedger.material_id.in_(material_ids))
        .order_by(StockLedger.created_at.desc(), StockLedger.id.desc())
        .all()
    )
    result: dict[int, StockLedger] = {}
    for row in rows:
        if row.material_id not in result:
            result[row.material_id] = row
    return result


def _stock_in_out(row: StockInRecord) -> StockInRecordOut:
    return StockInRecordOut(
        id=row.id,
        receipt_no=row.receipt_no,
        material_id=row.material_id,
        customer_id=row.customer_id,
        customer_name=row.customer_name,
        material_code=row.material_code,
        material_name=row.material_name,
        qty=row.qty,
        source=row.source,
        source_name=INBOUND_SOURCE_LABELS.get(row.source, row.source),
        operator=row.operator,
        giver=getattr(row, "giver", None),
        receiver=getattr(row, "receiver", None),
        remark=row.remark,
        created_at=row.created_at,
    )


def _require_warehouse(principal: AuthPrincipal) -> None:
    if not principal.is_warehouse:
        raise HTTPException(status_code=403, detail="仅仓库管理员可操作")


@router.get("/config")
def warehouse_config(principal: AuthPrincipal = Depends(require_system_auth)):
    from warehouse_excel import _path_is_dir_quick

    share_path = get_warehouse_share_path()
    try:
        share_dir = resolve_share_dir()
        accessible = _path_is_dir_quick(share_dir)
        resolved = str(share_dir)
    except Exception:
        accessible = False
        resolved = share_path
    return {
        "share_path": share_path,
        "share_resolved": resolved,
        "share_accessible": accessible,
        "role": principal.role,
        "department": principal.department,
    }


@router.get("/customers")
def warehouse_customers(db: Session = Depends(get_db)):
    names = {
        row.customer_id: row.customer_name
        for row in db.query(WarehouseMaterial.customer_id, WarehouseMaterial.customer_name).distinct()
    }
    for customer in load_config().get("customers", []):
        names[customer["id"]] = customer.get("name") or customer["id"]
    return [{"id": cid, "name": name} for cid, name in sorted(names.items(), key=lambda x: x[1])]


@router.get("/finished-goods", response_model=list[FinishedGoodsRowOut])
def finished_goods_list(
    customer_id: str = "",
    keyword: str = "",
    include_completed: bool = Query(False),
    only_with_inbound: bool = Query(False),
    limit: int = Query(2000, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """成品库存列表：客户/订单/机型/订单量/客户收货/入库/结存；待出库可发货。"""
    from finished_goods_service import list_finished_goods

    rows = list_finished_goods(
        db,
        customer_id=customer_id,
        keyword=keyword,
        include_completed=include_completed,
        only_with_inbound=only_with_inbound,
        limit=limit,
    )
    return [FinishedGoodsRowOut(**row) for row in rows]


@router.get("/materials", response_model=list[WarehouseMaterialOut])
def list_materials(
    customer_id: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
):
    from engineering_service import compute_kitting, find_bom_models_by_code, normalize_code as eng_norm
    from substitution_service import normalize_code as _norm

    q = db.query(WarehouseMaterial).order_by(WarehouseMaterial.customer_name, WarehouseMaterial.material_code)
    if customer_id:
        q = q.filter(WarehouseMaterial.customer_id == customer_id)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        q = q.filter(
            (WarehouseMaterial.material_code.like(like))
            | (WarehouseMaterial.material_name.like(like))
            | (WarehouseMaterial.spec.like(like))
        )
    rows = q.limit(500).all()

    # 料号未命中时，若关键字是机型号：优先按「已确认 BOM 的在制订单」展开（排除旧机型级共用）
    if kw and not rows:
        from engineering_service import list_bom_order_catalog

        needle = eng_norm(kw)
        order_rows = [
            r
            for r in list_bom_order_catalog(db, customer_id=customer_id or "", keyword=kw)
            if eng_norm(r.get("model_code")) == needle and r.get("id") and r.get("bom_status") == "imported"
        ]
        pick_id = order_rows[0]["id"] if len(order_rows) == 1 else None
        if pick_id is None and not order_rows:
            matches = find_bom_models_by_code(db, kw, customer_id or None)
            exact = [
                m
                for m in matches
                if eng_norm(m.model_code) == needle and (m.purchase_no or "").strip()
            ]
            if len(exact) == 1:
                pick_id = exact[0].id
        if pick_id is not None:
            try:
                kit = compute_kitting(db, int(pick_id), 1.0)
            except ValueError:
                kit = None
            if kit:
                from models import BomModel as _Bom

                bom_row = db.query(_Bom).filter(_Bom.id == pick_id).first()
                cid = (bom_row.customer_id if bom_row else "") or kit.get("customer_id") or ""
                stock_map = _customer_stock_map(db, cid)
                seen: set[int] = set()
                bom_rows: list[WarehouseMaterial] = []
                for line in kit.get("lines") or []:
                    code = eng_norm(line.get("material_code"))
                    primary = eng_norm(line.get("stock_primary_code") or line.get("material_code"))
                    mat = stock_map.get(code) or stock_map.get(primary)
                    if mat and mat.id not in seen:
                        seen.add(mat.id)
                        bom_rows.append(mat)
                rows = bom_rows

    ids = [row.id for row in rows]
    last_map = _latest_inbound_map(db, ids)
    last_op_map = _latest_ledger_map(db, ids)

    # 一次查出相关客户全部物料，构建库存映射（避免按客户多次查询）
    customer_ids = {row.customer_id for row in rows}
    stock_maps: dict[str, dict[str, WarehouseMaterial]] = {cid: {} for cid in customer_ids}
    if customer_ids:
        for mat in db.query(WarehouseMaterial).filter(WarehouseMaterial.customer_id.in_(customer_ids)).all():
            stock_maps[mat.customer_id][_norm(mat.material_code)] = mat

    return [
        _material_out(row, last_map.get(row.id), stock_maps.get(row.customer_id), last_op_map.get(row.id))
        for row in rows
    ]


@router.get("/materials/by-model", response_model=WarehouseModelMaterialsOut)
def list_materials_by_model(
    model_code: str = Query(..., min_length=1, description="机型号，如 120-200235-09"),
    order_qty: float = Query(1, ge=0, description="按套数换算需求量；选中订单后可用订单数量"),
    customer_id: Optional[str] = None,
    bom_model_id: Optional[int] = Query(None, ge=1),
    purchase_no: Optional[str] = Query(None, description="采购订单号，优先按订单确认的 BOM"),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """按机型/在制订单展开 BOM 用料。同机型多订单时按订单号区分，不共用机型级 BOM。"""
    from engineering_service import compute_kitting, list_bom_order_catalog, normalize_code as eng_norm
    from models import BomModel

    def _out_from_bom(bom_id: int, qty: float, purchase: str = "") -> WarehouseModelMaterialsOut:
        try:
            kit = compute_kitting(db, bom_id, qty)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        out = _kit_to_warehouse_model_out(db, kit)
        bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
        out.purchase_no = (purchase or (bom.purchase_no if bom else "") or "") or None
        return out

    if bom_model_id:
        bom = db.query(BomModel).filter(BomModel.id == bom_model_id).first()
        pn = (purchase_no or (bom.purchase_no if bom else "") or "").strip()
        return _out_from_bom(bom_model_id, order_qty, pn)

    needle = eng_norm(model_code)
    pn_filter = (purchase_no or "").strip()

    order_rows = [
        r
        for r in list_bom_order_catalog(db, customer_id=customer_id or "", keyword=model_code.strip())
        if eng_norm(r.get("model_code")) == needle
    ]
    if pn_filter:
        order_rows = [r for r in order_rows if (r.get("purchase_no") or "").strip() == pn_filter]

    imported = [r for r in order_rows if r.get("id") and r.get("bom_status") == "imported"]
    pending = [r for r in order_rows if r.get("bom_status") != "imported"]

    def _cand(r: dict) -> WarehouseBomModelCandidateOut:
        return WarehouseBomModelCandidateOut(
            id=int(r["id"] or 0),
            model_code=r.get("model_code") or "",
            model_name=r.get("model_name"),
            customer_id=r.get("customer_id") or "",
            customer_name=r.get("customer_name") or "",
            line_count=int(r.get("line_count") or 0),
            purchase_no=r.get("purchase_no") or "",
            order_qty=float(r.get("order_qty") or 0),
            bom_status=r.get("bom_status") or "pending",
        )

    # 仅 1 个在制且已确认 → 直接展开，并带上候选订单便于看清订单号
    if len(order_rows) == 1 and imported:
        row = imported[0]
        out = _out_from_bom(int(row["id"]), order_qty, row.get("purchase_no") or "")
        out.candidates = [_cand(r) for r in order_rows]
        return out

    if order_rows:
        all_cands = [_cand(r) for r in order_rows]
        msg = (
            f"机型「{model_code.strip()}」共 {len(order_rows)} 个在制订单"
            f"（已确认 BOM {len(imported)} / 待导入 {len(pending)}），请按订单号选择"
        )
        if not imported:
            msg = (
                f"机型「{model_code.strip()}」有 {len(pending)} 个在制订单，均尚未确认 BOM，"
                f"请先到工程管理按订单导入后再查用料"
            )
        return WarehouseModelMaterialsOut(
            matched=False,
            order_qty=order_qty,
            message=msg,
            candidates=all_cands,
        )

    return WarehouseModelMaterialsOut(
        matched=False,
        order_qty=order_qty,
        message=f"未找到机型「{model_code.strip()}」对应的在制订单",
    )


def _kit_to_warehouse_model_out(db: Session, kit: dict) -> WarehouseModelMaterialsOut:
    from engineering_service import normalize_code as eng_norm
    from models import BomModel

    cid = kit.get("customer_id") or ""
    stock_map = _customer_stock_map(db, cid) if cid else {}
    lines: list[WarehouseModelMaterialLineOut] = []
    for line in kit.get("lines") or []:
        code = eng_norm(line.get("material_code"))
        primary = eng_norm(line.get("stock_primary_code") or line.get("material_code"))
        mat = stock_map.get(code) or stock_map.get(primary)
        lines.append(
            WarehouseModelMaterialLineOut(
                material_id=mat.id if mat else None,
                material_code=line.get("material_code") or "",
                material_name=line.get("material_name"),
                spec=line.get("spec"),
                unit=line.get("unit") or "PCS",
                qty_per=float(line.get("qty_per") or 0),
                position=line.get("position"),
                required_qty=float(line.get("required_qty") or 0),
                stock_qty=float(line.get("stock_qty") or 0),
                available_qty=float(line.get("available_qty") or 0),
                shortage_qty=float(line.get("shortage_qty") or 0),
                status=str(line.get("status") or "unknown"),
                substitute_codes=list(line.get("substitute_codes") or []),
                excel_count_qty=line.get("excel_count_qty"),
                excel_in_qty=line.get("excel_in_qty"),
                excel_demand_qty=line.get("excel_demand_qty"),
                stock_primary_code=str(line.get("stock_primary_code") or ""),
            )
        )
    purchase_no = None
    bom_id = kit.get("bom_model_id")
    if bom_id:
        bom = db.query(BomModel).filter(BomModel.id == bom_id).first()
        if bom:
            purchase_no = (bom.purchase_no or "") or None
    return WarehouseModelMaterialsOut(
        matched=True,
        bom_model_id=kit.get("bom_model_id"),
        model_code=kit.get("model_code"),
        model_name=kit.get("model_name"),
        customer_id=kit.get("customer_id"),
        customer_name=kit.get("customer_name"),
        purchase_no=purchase_no,
        order_qty=float(kit.get("order_qty") or 1),
        material_status=str(kit.get("material_status") or "unknown"),
        ready_count=int(kit.get("ready_count") or 0),
        partial_count=int(kit.get("partial_count") or 0),
        shortage_count=int(kit.get("shortage_count") or 0),
        total_lines=int(kit.get("total_lines") or len(lines)),
        message=None,
        lines=lines,
    )


@router.get("/materials/{material_id}/detail", response_model=WarehouseMaterialDetailOut)
def get_material_detail_api(
    material_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    row = get_material(db, material_id)
    stock_map = _customer_stock_map(db, row.customer_id)
    last_map = _latest_inbound_map(db, [row.id])
    last_op_map = _latest_ledger_map(db, [row.id])
    detail = get_material_detail(db, material_id)
    detail["material"] = _material_out(row, last_map.get(row.id), stock_map, last_op_map.get(row.id))
    return detail


@router.get("/stock-ins", response_model=list[StockInRecordOut])
def list_stock_ins(
    customer_id: Optional[str] = None,
    material_id: Optional[int] = None,
    material_code: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    if not principal.is_warehouse and not principal.is_dept:
        raise HTTPException(status_code=403, detail="无权限")
    q = db.query(StockInRecord).order_by(StockInRecord.created_at.desc())
    if customer_id:
        q = q.filter(StockInRecord.customer_id == customer_id)
    if material_id:
        q = q.filter(StockInRecord.material_id == material_id)
    if material_code:
        q = q.filter(StockInRecord.material_code == material_code.strip())
    if source:
        q = q.filter(StockInRecord.source == source.strip())
    return [_stock_in_out(row) for row in q.limit(300).all()]


@router.post("/stock-in")
def api_stock_in(
    payload: StockInIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    stock_in(
        db,
        payload.material_id,
        payload.qty,
        principal.display_name or principal.username,
        payload.remark,
    )
    db.commit()
    return {"message": "来料入账成功"}


@router.post("/issues", response_model=StockIssueOut)
def api_create_issue(
    payload: StockIssueIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    issue = create_issue(
        db,
        payload.material_id,
        payload.qty,
        payload.department,
        principal.display_name or principal.username,
        payload.remark,
    )
    db.commit()
    db.refresh(issue)
    return issue


@router.get("/issues", response_model=list[StockIssueOut])
def list_issues(
    status: Optional[str] = None,
    department: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    q = db.query(StockIssue).order_by(StockIssue.created_at.desc())
    if principal.is_dept:
        q = q.filter(StockIssue.department == principal.department)
    elif department:
        q = q.filter(StockIssue.department == department.strip().lower())
    if status:
        q = q.filter(StockIssue.status == status)
    return q.limit(200).all()


@router.post("/issues/{issue_id}/confirm", response_model=StockIssueOut)
def api_confirm_issue(
    issue_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    if not principal.is_warehouse and not principal.is_dept:
        raise HTTPException(status_code=403, detail="无权限")
    issue = confirm_issue(db, issue_id, principal)
    db.commit()
    db.refresh(issue)
    return issue


@router.post("/issues/{issue_id}/reject", response_model=StockIssueOut)
def api_reject_issue(
    issue_id: int,
    remark: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    if not principal.is_warehouse and not principal.is_dept:
        raise HTTPException(status_code=403, detail="无权限")
    issue = reject_issue(db, issue_id, principal, remark)
    db.commit()
    db.refresh(issue)
    return issue


@router.post("/returns", response_model=StockReturnOut)
def api_create_return(
    payload: StockReturnIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    if not principal.is_dept:
        raise HTTPException(status_code=403, detail="仅部门账号可申请退料")
    row = create_return(
        db,
        payload.material_id,
        payload.qty,
        principal.department or "",
        principal.display_name or principal.username,
        payload.remark,
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/returns", response_model=list[StockReturnOut])
def list_returns(
    status: Optional[str] = None,
    department: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    q = db.query(StockReturn).order_by(StockReturn.created_at.desc())
    if principal.is_dept:
        q = q.filter(StockReturn.department == principal.department)
    elif department:
        q = q.filter(StockReturn.department == department.strip().lower())
    if status:
        q = q.filter(StockReturn.status == status)
    return q.limit(200).all()


@router.post("/returns/{return_id}/confirm", response_model=StockReturnOut)
def api_confirm_return(
    return_id: int,
    remark: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    row = confirm_return(db, return_id, principal.display_name or principal.username, remark)
    db.commit()
    db.refresh(row)
    return row


@router.post("/returns/{return_id}/reject", response_model=StockReturnOut)
def api_reject_return(
    return_id: int,
    remark: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    row = reject_return(db, return_id, principal.display_name or principal.username, remark)
    db.commit()
    db.refresh(row)
    return row


@router.get("/ledger", response_model=list[StockLedgerOut])
def list_ledger(
    customer_id: Optional[str] = None,
    material_code: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    q = db.query(StockLedger).order_by(StockLedger.created_at.desc())
    if customer_id:
        q = q.filter(StockLedger.customer_id == customer_id)
    if material_code:
        q = q.filter(StockLedger.material_code == material_code)
    return q.limit(300).all()


@router.get("/movements", response_model=list[WarehouseMovementOut])
def list_movements(
    customer_id: Optional[str] = None,
    order_no: Optional[str] = None,
    product_model: Optional[str] = None,
    movement_type: Optional[str] = None,
    material_id: Optional[int] = None,
    material_code: Optional[str] = None,
    keyword: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    q = db.query(WarehouseMovement).order_by(
        WarehouseMovement.doc_date.desc(),
        WarehouseMovement.id.desc(),
    )
    if customer_id:
        q = q.filter(WarehouseMovement.customer_id == customer_id)
    if order_no:
        q = q.filter(WarehouseMovement.order_no.contains(order_no.strip()))
    if product_model:
        q = q.filter(WarehouseMovement.product_model.contains(product_model.strip()))
    if movement_type:
        q = q.filter(WarehouseMovement.movement_type == movement_type.strip())
    if material_id:
        mat = get_material(db, material_id)
        q = q.filter(
            WarehouseMovement.customer_id == mat.customer_id,
            WarehouseMovement.material_code == mat.material_code,
        )
    elif material_code:
        q = q.filter(WarehouseMovement.material_code.contains(material_code.strip()))
    if keyword:
        kw = keyword.strip()
        q = q.filter(
            (WarehouseMovement.material_code.contains(kw))
            | (WarehouseMovement.material_name.contains(kw))
            | (WarehouseMovement.order_no.contains(kw))
            | (WarehouseMovement.product_model.contains(kw))
        )
    rows = q.limit(500).all()
    return [
        WarehouseMovementOut(
            id=row.id,
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            movement_type=row.movement_type,
            movement_type_name=MOVEMENT_LABELS.get(row.movement_type, row.movement_type),
            material_code=row.material_code,
            material_name=row.material_name,
            spec=row.spec,
            unit=row.unit or "PCS",
            qty=row.qty,
            qty_delta=row.qty_delta,
            order_no=row.order_no or "",
            product_model=row.product_model or "",
            order_qty=row.order_qty,
            process=row.process,
            doc_date=row.doc_date or "",
            ref_no=row.ref_no or "",
            source=row.source,
            operator=row.operator,
            remark=row.remark,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/operation-types")
def list_operation_types(
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    return [{"type": k, "label": v} for k, v in MOVEMENT_LABELS.items()]


@router.get("/snapshots", response_model=list[WorkbookSnapshotOut])
def list_workbook_snapshots(
    customer_id: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    q = db.query(WarehouseWorkbookSnapshot).order_by(WarehouseWorkbookSnapshot.synced_at.desc())
    if customer_id:
        q = q.filter(WarehouseWorkbookSnapshot.customer_id == customer_id)
    rows = q.limit(50).all()
    result = []
    for row in rows:
        try:
            names = json.loads(row.sheet_names or "[]")
        except json.JSONDecodeError:
            names = []
        result.append(
            WorkbookSnapshotOut(
                id=row.id,
                customer_id=row.customer_id,
                customer_name=row.customer_name,
                source_file=row.source_file,
                file_name=row.file_name,
                sheet_count=row.sheet_count,
                sheet_names=names,
                synced_at=row.synced_at,
            )
        )
    return result


@router.get("/snapshots/{snapshot_id}/sheets", response_model=list[SheetSnapshotMetaOut])
def list_snapshot_sheets(
    snapshot_id: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    rows = (
        db.query(WarehouseSheetSnapshot)
        .filter(WarehouseSheetSnapshot.snapshot_id == snapshot_id)
        .order_by(WarehouseSheetSnapshot.id)
        .all()
    )
    return [
        SheetSnapshotMetaOut(
            id=r.id,
            snapshot_id=r.snapshot_id,
            sheet_name=r.sheet_name,
            row_count=r.row_count,
            col_count=r.col_count,
        )
        for r in rows
    ]


@router.get("/snapshots/{snapshot_id}/sheets/{sheet_name}/data", response_model=SheetSnapshotDataOut)
def get_snapshot_sheet_data(
    snapshot_id: int,
    sheet_name: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(300, ge=1, le=2000),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    row = (
        db.query(WarehouseSheetSnapshot)
        .filter(
            WarehouseSheetSnapshot.snapshot_id == snapshot_id,
            WarehouseSheetSnapshot.sheet_name == sheet_name,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="工作表不存在")
    try:
        grid = json.loads(row.data_json or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="工作表数据损坏") from exc
    return SheetSnapshotDataOut(
        id=row.id,
        snapshot_id=row.snapshot_id,
        sheet_name=row.sheet_name,
        row_count=row.row_count,
        col_count=row.col_count,
        offset=offset,
        limit=limit,
        rows=grid[offset : offset + limit],
    )


@router.post("/operations", response_model=WarehouseMovementOut)
def create_operation(
    body: WarehouseOperationIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    row = apply_movement(
        db,
        body.material_id,
        body.movement_type,
        body.qty,
        principal.display_name or principal.username,
        order_no=body.order_no or "",
        product_model=body.product_model or "",
        order_qty=body.order_qty,
        process=body.process,
        ref_no=body.ref_no or "",
        remark=body.remark or "",
        doc_date=body.doc_date,
        department=body.department,
        giver=body.giver or "",
        receiver=body.receiver or "",
    )
    db.commit()
    db.refresh(row)
    return _movement_out(row)


@router.post("/batch-inbound", response_model=BatchOperationResultOut)
def api_batch_inbound(
    body: BatchInboundIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    result = batch_inbound(
        db,
        body.customer_id.strip(),
        [item.model_dump() for item in body.items],
        principal.display_name or principal.username,
        ref_no=body.ref_no or "",
        remark=body.remark or "",
        giver=body.giver or "",
        receiver=body.receiver or "",
    )
    db.commit()
    return _batch_result_out(result)


@router.post("/batch-inbound/parse-excel", response_model=BatchInboundParseOut)
async def api_parse_inbound_excel(
    file: UploadFile = File(...),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx）")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        parsed = parse_inbound_excel(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchInboundParseOut(
        items=[BatchInboundLineIn(**item) for item in parsed["items"]],
        errors=parsed.get("errors") or [],
        parsed_count=parsed.get("parsed_count") or 0,
        header_row=parsed.get("header_row"),
    )


@router.get("/inbound-template")
def download_inbound_template(principal: AuthPrincipal = Depends(require_system_auth)):
    _require_warehouse(principal)
    wb = build_inbound_template_workbook()
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="inbound_template.xlsx"'},
    )


@router.get("/orders/{line_key}/issue-preview", response_model=OrderIssuePreviewOut)
def api_order_issue_preview(
    line_key: str,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    return get_order_issue_preview(db, line_key)


@router.get("/orders/{line_key}/issue-template")
def download_issue_template(
    line_key: str,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    preview = get_order_issue_preview(db, line_key)
    if not preview.get("lines"):
        raise HTTPException(status_code=400, detail=preview.get("message") or "无发料清单可导出")
    wb = build_issue_template_workbook(preview)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = issue_template_filename(preview)
    from urllib.parse import quote

    ascii_name = quote(filename)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{ascii_name}"},
    )


@router.post("/orders/{line_key}/batch-issue/parse-excel", response_model=BatchIssueParseOut)
async def api_parse_issue_excel(
    line_key: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    filename = (file.filename or "").lower()
    if not filename.endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="请上传 Excel 文件（.xlsx）")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    preview = get_order_issue_preview(db, line_key)
    try:
        parsed = parse_issue_excel(content, preview)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BatchIssueParseOut(
        lines=[BatchIssueImportLineOut(**line) for line in parsed["lines"]],
        errors=parsed.get("errors") or [],
        parsed_count=parsed.get("parsed_count") or 0,
        header_row=parsed.get("header_row"),
    )


@router.post("/orders/{line_key}/batch-issue", response_model=BatchOperationResultOut)
def api_batch_issue(
    line_key: str,
    body: BatchIssueIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    result = batch_issue_order(
        db,
        line_key,
        [item.model_dump() for item in body.lines],
        principal.display_name or principal.username,
        ref_no=body.ref_no or "",
        remark=body.remark or "",
        skip_shortage=body.skip_shortage,
        giver=body.giver or "",
        receiver=body.receiver or "",
    )
    db.commit()
    return _batch_result_out(result)


@router.post("/sync-now")
def api_sync_now(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    try:
        summary, logs = sync_warehouse_materials(db)
        db.commit()
        return {
            "message": summary,
            "files": [
                ExcelImportResult(
                    source_file=log.source_file,
                    customer_name=log.customer_name,
                    rows_imported=log.rows_imported,
                    rows_updated=log.rows_updated,
                    status=log.status,
                    message=log.message,
                )
                for log in logs
            ],
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"共享盘目录无权访问: {exc}。请用本机终端重启后端并授予桌面文件夹访问权限",
        ) from exc


@router.post("/import-excel", response_model=list[ExcelImportResult])
def api_import_excel(
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    """兼容旧接口：等同共享盘同步"""
    _require_warehouse(principal)
    try:
        _, logs = sync_warehouse_materials(db)
        db.commit()
        return [
            ExcelImportResult(
                source_file=log.source_file,
                customer_name=log.customer_name,
                rows_imported=log.rows_imported,
                rows_updated=log.rows_updated,
                status=log.status,
                message=log.message,
            )
            for log in logs
        ]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"共享盘目录无权访问: {exc}。请用本机终端重启后端并授予桌面文件夹访问权限",
        ) from exc


@router.get("/import-logs", response_model=list[ExcelImportResult])
def import_logs(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_system_auth)):
    _require_warehouse(principal)
    rows = db.query(ExcelImportLog).order_by(ExcelImportLog.created_at.desc()).limit(50).all()
    return [
        ExcelImportResult(
            source_file=r.source_file,
            customer_name=r.customer_name,
            rows_imported=r.rows_imported,
            rows_updated=r.rows_updated,
            status=r.status,
            message=r.message,
        )
        for r in rows
    ]


@router.get("/template")
def download_template(principal: AuthPrincipal = Depends(require_system_auth)):
    _require_warehouse(principal)
    wb = build_template_workbook()
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="_模板.xlsx"'},
    )


@router.get("/export-inventory")
def export_inventory(
    customer_id: Optional[str] = None,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_warehouse(principal)
    wb = export_inventory_workbook(db, customer_id)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="库存导出.xlsx"'},
    )


@router.get("/dept/summary")
def dept_summary(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_system_auth)):
    if not principal.is_dept:
        raise HTTPException(status_code=403, detail="仅部门账号可访问")
    dept = principal.department
    pending_issues = (
        db.query(StockIssue)
        .filter(StockIssue.department == dept, StockIssue.status == ISSUE_STATUS_PENDING)
        .count()
    )
    pending_returns = (
        db.query(StockReturn)
        .filter(StockReturn.department == dept, StockReturn.status == RETURN_STATUS_PENDING)
        .count()
    )
    return {
        "department": dept,
        "display_name": principal.display_name,
        "pending_issues": pending_issues,
        "pending_returns": pending_returns,
    }
