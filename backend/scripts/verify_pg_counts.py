#!/usr/bin/env python3
"""对比 SQLite 与 Postgres 各表行数。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


def counts(url: str) -> dict[str, int]:
    kw = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, **kw)
    insp = inspect(eng)
    out = {}
    with eng.connect() as c:
        for t in insp.get_table_names():
            if t.startswith("sqlite_"):
                continue
            out[t] = int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() or 0)
    return out


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "ems.db")
    pg = (os.environ.get("DATABASE_URL") or "").strip()
    if not pg:
        print("请设置 DATABASE_URL")
        return 2
    sc = counts(f"sqlite:///{src}")
    pc = counts(pg)
    tables = sorted(set(sc) | set(pc))
    bad = 0
    print(f"{'table':40s} {'sqlite':>10s} {'postgres':>10s} {'delta':>8s}")
    for t in tables:
        a, b = sc.get(t), pc.get(t)
        if a is None or b is None:
            print(f"{t:40s} {str(a):>10s} {str(b):>10s} {'MISS':>8s}")
            bad += 1
            continue
        d = b - a
        mark = "" if d == 0 else " <<"
        if d != 0:
            bad += 1
        print(f"{t:40s} {a:10d} {b:10d} {d:8d}{mark}")
    print("---")
    print("mismatches", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
