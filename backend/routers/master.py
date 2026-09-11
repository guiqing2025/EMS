"""主数据 API：客户 / 供应商 / 仓库 / 库存产品 / 价格 / 单据编号（阶段 0）"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
from doc_number import list_doc_number_rules, next_doc_number
from master_data_service import (
    customer_to_dict,
    ensure_master_defaults,
    soft_deactivate,
    supplier_to_dict,
    touch,
)
from models import ErpCustomer, ErpPriceItem, ErpStockProduct, ErpSupplier, ErpWarehouse
from system_auth import AuthPrincipal, require_system_auth

router = APIRouter(
    prefix="/api/master",
    tags=["master"],
    dependencies=[Depends(require_system_auth)],
)

WRITE_ROLES = frozenset(
    {
        "admin",
        "pmc",
        "planner",
        "sales",
        "purchasing",
        "warehouse",
        "finance",
    }
)

CERT_KINDS = {
    "business": "cert_business",
    "org": "cert_org",
    "tax": "cert_tax",
}
ALLOWED_CERT_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
UPLOADS_CUSTOMERS = STATIC_DIR / "uploads" / "customers"


def _require_write(principal: AuthPrincipal) -> None:
    if principal.role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="无主数据维护权限")


def _safe_ext(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_CERT_EXT:
        raise HTTPException(status_code=400, detail="仅支持 jpg/png/webp/gif 图片")
    return ext


def _unlink_rel(rel: str) -> None:
    rel = (rel or "").strip()
    if not rel or ".." in rel:
        return
    path = STATIC_DIR / rel
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


class PartnerIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    short_name: str = ""
    contact: str = ""
    phone: str = ""
    address: str = ""
    tax_no: str = ""
    remark: str = ""
    is_active: bool = True


class WarehouseIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=64)
    wh_type: str = "good"
    remark: str = ""
    is_active: bool = True
    sort_no: int = 0


class StockProductIn(BaseModel):
    material_code: str = Field(..., min_length=1, max_length=128)
    material_name: str = ""
    spec: str = ""
    unit: str = "PCS"
    category: str = ""
    can_stock: bool = True
    safety_qty: float = 0
    remark: str = ""
    is_active: bool = True


class PriceIn(BaseModel):
    price_type: str = "standard"
    customer_id: Optional[int] = None
    material_code: str = Field(..., min_length=1, max_length=128)
    material_name: str = ""
    unit_price: float = 0
    currency: str = "CNY"
    effective_from: str = ""
    effective_to: str = ""
    remark: str = ""
    is_active: bool = True


class DocPreviewIn(BaseModel):
    doc_type: str


@router.get("/bootstrap")
def bootstrap(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_system_auth)):
    stats = ensure_master_defaults(db)
    db.commit()
    return {
        "ok": True,
        "seeded": stats,
        "roles_hint": ["sales", "purchasing", "production", "quality", "pmc", "finance", "warehouse"],
        "srm_orders_policy": "legacy_readonly_optional",
        "message": "主数据默认仓库与单据编号规则已就绪；新业务以销售订单为主轴，历史客户 PO 仅作对照。",
    }


# —— 客户 ——


@router.get("/customers")
def list_customers(
    q: str = "",
    active_only: bool = True,
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    ensure_master_defaults(db)
    query = db.query(ErpCustomer)
    if active_only:
        query = query.filter(ErpCustomer.is_active.is_(True))
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(ErpCustomer.code).like(like),
                func.lower(ErpCustomer.name).like(like),
                func.lower(ErpCustomer.short_name).like(like),
            )
        )
    rows = query.order_by(ErpCustomer.code).limit(limit).all()
    return {"total": len(rows), "items": [customer_to_dict(r) for r in rows]}


@router.get("/customers/{cid}")
def get_customer(cid: int, db: Session = Depends(get_db), _: AuthPrincipal = Depends(require_system_auth)):
    row = db.query(ErpCustomer).filter(ErpCustomer.id == cid).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer_to_dict(row)


@router.post("/customers")
def create_customer(
    body: PartnerIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    code = body.code.strip()
    if db.query(ErpCustomer).filter(ErpCustomer.code == code).first():
        raise HTTPException(status_code=400, detail="客户编码已存在")
    row = ErpCustomer(
        code=code,
        name=body.name.strip(),
        short_name=(body.short_name or "").strip(),
        contact=(body.contact or "").strip(),
        phone=(body.phone or "").strip(),
        address=(body.address or "").strip(),
        tax_no=(body.tax_no or "").strip(),
        remark=(body.remark or "").strip(),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return customer_to_dict(row)


@router.put("/customers/{cid}")
def update_customer(
    cid: int,
    body: PartnerIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpCustomer).filter(ErpCustomer.id == cid).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    new_code = body.code.strip()
    clash = db.query(ErpCustomer).filter(ErpCustomer.code == new_code, ErpCustomer.id != cid).first()
    if clash:
        raise HTTPException(status_code=400, detail="客户编码已存在")
    row.code = new_code
    row.name = body.name.strip()
    row.short_name = (body.short_name or "").strip()
    row.contact = (body.contact or "").strip()
    row.phone = (body.phone or "").strip()
    row.address = (body.address or "").strip()
    row.tax_no = (body.tax_no or "").strip()
    row.remark = (body.remark or "").strip()
    row.is_active = body.is_active
    touch(row)
    db.commit()
    db.refresh(row)
    return customer_to_dict(row)


@router.post("/customers/{cid}/certs/{kind}")
async def upload_customer_cert(
    cid: int,
    kind: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    field = CERT_KINDS.get(kind)
    if not field:
        raise HTTPException(status_code=400, detail="证照类型无效，应为 business/org/tax")
    row = db.query(ErpCustomer).filter(ErpCustomer.id == cid).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    ext = _safe_ext(file.filename or "")
    dest_dir = UPLOADS_CUSTOMERS / str(cid)
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{kind}_{uuid.uuid4().hex[:12]}{ext}"
    dest = dest_dir / fname
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 8MB")
    dest.write_bytes(raw)
    rel = f"uploads/customers/{cid}/{fname}"
    old = getattr(row, field, "") or ""
    setattr(row, field, rel)
    touch(row)
    db.commit()
    db.refresh(row)
    if old and old != rel:
        _unlink_rel(old)
    return customer_to_dict(row)


@router.delete("/customers/{cid}/certs/{kind}")
def delete_customer_cert(
    cid: int,
    kind: str,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    field = CERT_KINDS.get(kind)
    if not field:
        raise HTTPException(status_code=400, detail="证照类型无效，应为 business/org/tax")
    row = db.query(ErpCustomer).filter(ErpCustomer.id == cid).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    old = getattr(row, field, "") or ""
    setattr(row, field, "")
    touch(row)
    db.commit()
    db.refresh(row)
    if old:
        _unlink_rel(old)
    return customer_to_dict(row)


@router.delete("/customers/{cid}")
def delete_customer(
    cid: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpCustomer).filter(ErpCustomer.id == cid).first()
    if not row:
        raise HTTPException(status_code=404, detail="客户不存在")
    soft_deactivate(row)
    db.commit()
    return {"ok": True}


# —— 供应商 ——


@router.get("/suppliers")
def list_suppliers(
    q: str = "",
    active_only: bool = True,
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    ensure_master_defaults(db)
    query = db.query(ErpSupplier)
    if active_only:
        query = query.filter(ErpSupplier.is_active.is_(True))
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(ErpSupplier.code).like(like),
                func.lower(ErpSupplier.name).like(like),
                func.lower(ErpSupplier.short_name).like(like),
            )
        )
    rows = query.order_by(ErpSupplier.code).limit(limit).all()
    return {"total": len(rows), "items": [supplier_to_dict(r) for r in rows]}


@router.post("/suppliers")
def create_supplier(
    body: PartnerIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    code = body.code.strip()
    if db.query(ErpSupplier).filter(ErpSupplier.code == code).first():
        raise HTTPException(status_code=400, detail="供应商编码已存在")
    row = ErpSupplier(
        code=code,
        name=body.name.strip(),
        short_name=(body.short_name or "").strip(),
        contact=(body.contact or "").strip(),
        phone=(body.phone or "").strip(),
        address=(body.address or "").strip(),
        tax_no=(body.tax_no or "").strip(),
        remark=(body.remark or "").strip(),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return supplier_to_dict(row)


@router.put("/suppliers/{sid}")
def update_supplier(
    sid: int,
    body: PartnerIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpSupplier).filter(ErpSupplier.id == sid).first()
    if not row:
        raise HTTPException(status_code=404, detail="供应商不存在")
    new_code = body.code.strip()
    clash = db.query(ErpSupplier).filter(ErpSupplier.code == new_code, ErpSupplier.id != sid).first()
    if clash:
        raise HTTPException(status_code=400, detail="供应商编码已存在")
    row.code = new_code
    row.name = body.name.strip()
    row.short_name = (body.short_name or "").strip()
    row.contact = (body.contact or "").strip()
    row.phone = (body.phone or "").strip()
    row.address = (body.address or "").strip()
    row.tax_no = (body.tax_no or "").strip()
    row.remark = (body.remark or "").strip()
    row.is_active = body.is_active
    touch(row)
    db.commit()
    db.refresh(row)
    return supplier_to_dict(row)


@router.delete("/suppliers/{sid}")
def delete_supplier(
    sid: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpSupplier).filter(ErpSupplier.id == sid).first()
    if not row:
        raise HTTPException(status_code=404, detail="供应商不存在")
    soft_deactivate(row)
    db.commit()
    return {"ok": True}


# —— 仓库 ——


def _wh_dict(row: ErpWarehouse) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "wh_type": row.wh_type,
        "remark": row.remark or "",
        "is_active": bool(row.is_active),
        "sort_no": row.sort_no,
        "created_at": row.created_at,
    }


@router.get("/warehouses")
def list_warehouses(
    active_only: bool = True,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    ensure_master_defaults(db)
    db.commit()
    query = db.query(ErpWarehouse)
    if active_only:
        query = query.filter(ErpWarehouse.is_active.is_(True))
    rows = query.order_by(ErpWarehouse.sort_no, ErpWarehouse.code).all()
    return {"total": len(rows), "items": [_wh_dict(r) for r in rows]}


@router.post("/warehouses")
def create_warehouse(
    body: WarehouseIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    code = body.code.strip().upper()
    if db.query(ErpWarehouse).filter(ErpWarehouse.code == code).first():
        raise HTTPException(status_code=400, detail="仓库编码已存在")
    row = ErpWarehouse(
        code=code,
        name=body.name.strip(),
        wh_type=(body.wh_type or "good").strip(),
        remark=(body.remark or "").strip(),
        is_active=body.is_active,
        sort_no=body.sort_no,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _wh_dict(row)


@router.put("/warehouses/{wid}")
def update_warehouse(
    wid: int,
    body: WarehouseIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpWarehouse).filter(ErpWarehouse.id == wid).first()
    if not row:
        raise HTTPException(status_code=404, detail="仓库不存在")
    code = body.code.strip().upper()
    clash = db.query(ErpWarehouse).filter(ErpWarehouse.code == code, ErpWarehouse.id != wid).first()
    if clash:
        raise HTTPException(status_code=400, detail="仓库编码已存在")
    row.code = code
    row.name = body.name.strip()
    row.wh_type = (body.wh_type or "good").strip()
    row.remark = (body.remark or "").strip()
    row.is_active = body.is_active
    row.sort_no = body.sort_no
    db.commit()
    db.refresh(row)
    return _wh_dict(row)


# —— 库存产品 ——


def _sp_dict(row: ErpStockProduct) -> dict:
    return {
        "id": row.id,
        "material_code": row.material_code,
        "material_name": row.material_name or "",
        "spec": row.spec or "",
        "unit": row.unit or "PCS",
        "category": row.category or "",
        "can_stock": bool(row.can_stock),
        "safety_qty": float(row.safety_qty or 0),
        "remark": row.remark or "",
        "is_active": bool(row.is_active),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/stock-products")
def list_stock_products(
    q: str = "",
    active_only: bool = True,
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    query = db.query(ErpStockProduct)
    if active_only:
        query = query.filter(ErpStockProduct.is_active.is_(True))
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(ErpStockProduct.material_code).like(like),
                func.lower(ErpStockProduct.material_name).like(like),
            )
        )
    rows = query.order_by(ErpStockProduct.material_code).limit(limit).all()
    return {"total": len(rows), "items": [_sp_dict(r) for r in rows]}


@router.post("/stock-products")
def create_stock_product(
    body: StockProductIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    code = body.material_code.strip()
    if db.query(ErpStockProduct).filter(ErpStockProduct.material_code == code).first():
        raise HTTPException(status_code=400, detail="物料编码已存在")
    row = ErpStockProduct(
        material_code=code,
        material_name=(body.material_name or "").strip(),
        spec=(body.spec or "").strip(),
        unit=(body.unit or "PCS").strip(),
        category=(body.category or "").strip(),
        can_stock=body.can_stock,
        safety_qty=float(body.safety_qty or 0),
        remark=(body.remark or "").strip(),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _sp_dict(row)


@router.put("/stock-products/{pid}")
def update_stock_product(
    pid: int,
    body: StockProductIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpStockProduct).filter(ErpStockProduct.id == pid).first()
    if not row:
        raise HTTPException(status_code=404, detail="库存产品不存在")
    code = body.material_code.strip()
    clash = (
        db.query(ErpStockProduct)
        .filter(ErpStockProduct.material_code == code, ErpStockProduct.id != pid)
        .first()
    )
    if clash:
        raise HTTPException(status_code=400, detail="物料编码已存在")
    row.material_code = code
    row.material_name = (body.material_name or "").strip()
    row.spec = (body.spec or "").strip()
    row.unit = (body.unit or "PCS").strip()
    row.category = (body.category or "").strip()
    row.can_stock = body.can_stock
    row.safety_qty = float(body.safety_qty or 0)
    row.remark = (body.remark or "").strip()
    row.is_active = body.is_active
    touch(row)
    db.commit()
    db.refresh(row)
    return _sp_dict(row)


@router.delete("/stock-products/{pid}")
def delete_stock_product(
    pid: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpStockProduct).filter(ErpStockProduct.id == pid).first()
    if not row:
        raise HTTPException(status_code=404, detail="库存产品不存在")
    soft_deactivate(row)
    db.commit()
    return {"ok": True}


# —— 价格 ——


def _price_dict(row: ErpPriceItem) -> dict:
    return {
        "id": row.id,
        "price_type": row.price_type,
        "customer_id": row.customer_id,
        "material_code": row.material_code,
        "material_name": row.material_name or "",
        "unit_price": float(row.unit_price or 0),
        "currency": row.currency or "CNY",
        "effective_from": row.effective_from or "",
        "effective_to": row.effective_to or "",
        "remark": row.remark or "",
        "is_active": bool(row.is_active),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/prices")
def list_prices(
    q: str = "",
    price_type: str = "",
    active_only: bool = True,
    limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    query = db.query(ErpPriceItem)
    if active_only:
        query = query.filter(ErpPriceItem.is_active.is_(True))
    if price_type.strip():
        query = query.filter(ErpPriceItem.price_type == price_type.strip())
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(ErpPriceItem.material_code).like(like),
                func.lower(ErpPriceItem.material_name).like(like),
            )
        )
    rows = query.order_by(ErpPriceItem.material_code).limit(limit).all()
    return {"total": len(rows), "items": [_price_dict(r) for r in rows]}


@router.post("/prices")
def create_price(
    body: PriceIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = ErpPriceItem(
        price_type=(body.price_type or "standard").strip(),
        customer_id=body.customer_id,
        material_code=body.material_code.strip(),
        material_name=(body.material_name or "").strip(),
        unit_price=float(body.unit_price or 0),
        currency=(body.currency or "CNY").strip(),
        effective_from=(body.effective_from or "").strip(),
        effective_to=(body.effective_to or "").strip(),
        remark=(body.remark or "").strip(),
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _price_dict(row)


@router.put("/prices/{pid}")
def update_price(
    pid: int,
    body: PriceIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpPriceItem).filter(ErpPriceItem.id == pid).first()
    if not row:
        raise HTTPException(status_code=404, detail="价格记录不存在")
    row.price_type = (body.price_type or "standard").strip()
    row.customer_id = body.customer_id
    row.material_code = body.material_code.strip()
    row.material_name = (body.material_name or "").strip()
    row.unit_price = float(body.unit_price or 0)
    row.currency = (body.currency or "CNY").strip()
    row.effective_from = (body.effective_from or "").strip()
    row.effective_to = (body.effective_to or "").strip()
    row.remark = (body.remark or "").strip()
    row.is_active = body.is_active
    touch(row)
    db.commit()
    db.refresh(row)
    return _price_dict(row)


@router.delete("/prices/{pid}")
def delete_price(
    pid: int,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    row = db.query(ErpPriceItem).filter(ErpPriceItem.id == pid).first()
    if not row:
        raise HTTPException(status_code=404, detail="价格记录不存在")
    soft_deactivate(row)
    db.commit()
    return {"ok": True}


# —— 单据编号 ——


@router.get("/doc-numbers")
def get_doc_numbers(db: Session = Depends(get_db), principal: AuthPrincipal = Depends(require_system_auth)):
    rows = list_doc_number_rules(db)
    db.commit()
    return {
        "items": [
            {
                "doc_type": r.doc_type,
                "prefix": r.prefix,
                "name": r.name,
                "date_fmt": r.date_fmt,
                "seq_width": r.seq_width,
                "last_date": r.last_date,
                "last_seq": r.last_seq,
            }
            for r in rows
        ]
    }


@router.post("/doc-numbers/preview")
def preview_doc_number(
    body: DocPreviewIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(require_system_auth),
):
    _require_write(principal)
    try:
        no = next_doc_number(db, body.doc_type.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"doc_type": body.doc_type, "doc_no": no, "generated_at": datetime.utcnow().isoformat()}
