# -*- coding: utf-8 -*-
"""CLI：工程资料自查（与 API /engineering/audit 同源）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import SessionLocal
from eng_audit_service import build_eng_audit_xlsx, run_eng_data_audit

OUT_DIR = ROOT / "data" / "audit"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    db = SessionLocal()
    try:
        audit = run_eng_data_audit(db)
    finally:
        db.close()

    out_json = OUT_DIR / f"eng_audit_{ts}.json"
    out_xlsx = OUT_DIR / f"eng_audit_{ts}.xlsx"
    out_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    out_xlsx.write_bytes(build_eng_audit_xlsx(audit))

    s = audit["summary"]
    print(f"OK substitution_issues={s['substitution_qty_issue_count']} orders={s['substitution_affected_orders']}")
    print(f"OK bom_total={s['bom_total']} leak={s['bom_leak']} ok={s['bom_ok']}")
    print(f"OK reprint_orders={s['reprint_order_count']} wrong_logs={s['wrong_print_log_rows']}")
    print(f"JSON: {out_json}")
    print(f"XLSX: {out_xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
