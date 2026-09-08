# -*- coding: utf-8 -*-
"""Compare SQLAlchemy models vs SQLite columns; print missing/extra."""
from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, r"C:\EMS\backend")
os.chdir(r"C:\EMS\backend")
os.environ.setdefault("EMS_USE_SQLITE", "1")
os.environ.setdefault("EMS_DB", "ems.db")
os.environ.setdefault("EMS_ALLOW_DEV_DB", "1")

import models  # noqa: E402
from sqlalchemy.orm import DeclarativeBase  # noqa: E402

Base = models.Base
conn = sqlite3.connect("ems.db")
existing = {
    r[0]
    for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
}

print("=== model vs sqlite schema ===")
issues = 0
for table in Base.metadata.sorted_tables:
    name = table.name
    mapped = [c.name for c in table.columns]
    if name not in existing:
        print(f"MISSING TABLE {name}")
        issues += 1
        continue
    have = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
    miss = [c for c in mapped if c not in have]
    extra = [c for c in have if c not in mapped]
    if miss or extra:
        issues += 1
        print(f"{name}: missing={miss} extra={extra}")
print(f"tables_checked={len(Base.metadata.tables)} issue_tables={issues}")
