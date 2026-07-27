"""替代料规则：旧文件一次性迁入（按客户，默认 feilisi）。"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from config import get_substitution_file_path
from models import SubstitutionRule
from substitution_import import parse_xlsx_bytes
from substitution_service import reload_substitution_cache_from_db

logger = logging.getLogger(__name__)


def sync_substitution_rules(
    db: Session,
    *,
    customer_id: str = "feilisi",
    replace: bool = True,
) -> dict:
    """从配置的旧替代表文件迁入指定客户（覆盖或追加）。"""
    cid = (customer_id or "feilisi").strip() or "feilisi"
    path = Path(get_substitution_file_path())
    if not path.is_file():
        return {
            "status": "error",
            "message": f"替代料文件不存在: {path}",
            "rows_imported": 0,
            "source_file": str(path),
            "synced_at": None,
            "customer_id": cid,
        }

    parsed = parse_xlsx_bytes(path.read_bytes())
    rows = parsed.get("rows") or []
    now = datetime.utcnow()
    if replace:
        db.query(SubstitutionRule).filter(SubstitutionRule.customer_id == cid).delete(
            synchronize_session=False
        )
    for item in rows:
        db.add(
            SubstitutionRule(
                customer_id=cid,
                **item,
                source_type="legacy_migrate",
                source_file=str(path),
                import_batch_id=None,
                synced_at=now,
            )
        )
    db.flush()
    reload_substitution_cache_from_db(db, cid)
    logger.info("替代料规则已迁入 %s: %s 行, 文件 %s", cid, len(rows), path.name)
    return {
        "status": "success",
        "message": f"已迁入 {cid} 共 {len(rows)} 条替代料规则",
        "rows_imported": len(rows),
        "source_file": str(path),
        "synced_at": now,
        "customer_id": cid,
    }
