"""景立 ERP 阶段 0：主数据种子与通用读写辅助"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Type, TypeVar

from sqlalchemy.orm import Session

from doc_number import ensure_doc_number_defaults
from models import ErpCustomer, ErpSupplier, ErpWarehouse

T = TypeVar("T")

DEFAULT_WAREHOUSES = [
    ("GOOD", "良品仓", "good", 10),
    ("INSPECT", "待检仓", "inspect", 20),
    ("RETURN", "退货仓", "return", 30),
    ("WIP", "在制仓", "wip", 40),
]


def ensure_master_defaults(db: Session) -> dict[str, int]:
    wh_n = 0
    for code, name, wh_type, sort_no in DEFAULT_WAREHOUSES:
        row = db.query(ErpWarehouse).filter(ErpWarehouse.code == code).first()
        if row:
            continue
        db.add(
            ErpWarehouse(
                code=code,
                name=name,
                wh_type=wh_type,
                sort_no=sort_no,
                is_active=True,
            )
        )
        wh_n += 1
    doc_n = ensure_doc_number_defaults(db)
    db.flush()
    return {"warehouses": wh_n, "doc_rules": doc_n}


def _now() -> datetime:
    return datetime.utcnow()


def get_by_code(db: Session, model: Type[T], code: str) -> Optional[T]:
    return db.query(model).filter(model.code == code.strip()).first()  # type: ignore[attr-defined]


def soft_deactivate(row: Any) -> None:
    row.is_active = False
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def touch(row: Any) -> None:
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def customer_to_dict(row: ErpCustomer) -> dict:
    def _url(rel: str) -> str:
        p = (rel or "").strip()
        if not p:
            return ""
        if p.startswith("http://") or p.startswith("https://") or p.startswith("/"):
            return p
        return f"/static/{p.lstrip('/')}"

    cert_business = getattr(row, "cert_business", None) or ""
    cert_org = getattr(row, "cert_org", None) or ""
    cert_tax = getattr(row, "cert_tax", None) or ""
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "short_name": row.short_name or "",
        "contact": row.contact or "",
        "phone": row.phone or "",
        "address": row.address or "",
        "tax_no": row.tax_no or "",
        "remark": row.remark or "",
        "cert_business": cert_business,
        "cert_org": cert_org,
        "cert_tax": cert_tax,
        "cert_business_url": _url(cert_business),
        "cert_org_url": _url(cert_org),
        "cert_tax_url": _url(cert_tax),
        "is_active": bool(row.is_active),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def supplier_to_dict(row: ErpSupplier) -> dict:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "short_name": row.short_name or "",
        "contact": row.contact or "",
        "phone": row.phone or "",
        "address": row.address or "",
        "tax_no": row.tax_no or "",
        "remark": row.remark or "",
        "is_active": bool(row.is_active),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
