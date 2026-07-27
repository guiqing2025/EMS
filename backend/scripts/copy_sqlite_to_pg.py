#!/usr/bin/env python3
"""SQLite → PostgreSQL 全量拷贝（不依赖 pgloader）。

用法（先起好空库 ems_prod）：
  DATABASE_URL=postgresql+psycopg://ems:PASS@127.0.0.1:5432/ems_prod \\
    .venv/bin/python scripts/copy_sqlite_to_pg.py [/path/to/ems.db]
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if not (os.environ.get("DATABASE_URL") or "").strip():
    print("请设置 DATABASE_URL 指向目标 Postgres")
    raise SystemExit(2)

from database import Base, engine as pg_engine  # noqa: E402
import models  # noqa: F401,E402


def _coerce(val, col_type: str):
    if val is None:
        return None
    t = (col_type or "").lower()
    if t in ("boolean", "bool"):
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(int(val))
        s = str(val).strip().lower()
        if s in ("1", "true", "t", "yes", "y"):
            return True
        if s in ("0", "false", "f", "no", "n", ""):
            return False
        return bool(val)
    if t.startswith("timestamp") or t == "datetime":
        if isinstance(val, datetime):
            return val
        if isinstance(val, date):
            return datetime(val.year, val.month, val.day)
        # sqlite 可能存字符串
        return val
    return val


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "ems.db")
    if not src.is_file():
        print("找不到源库", src)
        return 2

    sqlite_url = f"sqlite:///{src}"
    src_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

    print("源:", src, "大小MB", round(src.stat().st_size / 1024 / 1024, 1))
    print("目标:", pg_engine.url.render_as_string(hide_password=True))

    Base.metadata.create_all(bind=pg_engine)

    # SQLite 不强制 VARCHAR 长度；迁库前把 PG 的 varchar 放宽为 TEXT，避免截断
    with pg_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND data_type = 'character varying'
                """
            )
        ).fetchall()
        for tname, cname in rows:
            conn.execute(
                text(f'ALTER TABLE "{tname}" ALTER COLUMN "{cname}" TYPE TEXT')
            )
        print(f"已放宽 {len(rows)} 个 varchar → TEXT")

    src_insp = inspect(src_engine)
    pg_insp = inspect(pg_engine)
    src_tables = set(src_insp.get_table_names())
    pg_tables = set(pg_insp.get_table_names())
    tables = sorted(src_tables & pg_tables)
    tables = [t for t in tables if not t.startswith("sqlite_")]

    # FK 旁路（需 SUPERUSER；迁库临时授权）
    with pg_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = replica"))
        conn.commit()

    batch = 1000
    summary = []
    for table in tables:
        src_cols = [c["name"] for c in src_insp.get_columns(table)]
        pg_col_meta = {c["name"]: c for c in pg_insp.get_columns(table)}
        cols = [c for c in src_cols if c in pg_col_meta]
        if not cols:
            print("SKIP empty cols", table)
            continue
        type_map = {c: str(pg_col_meta[c]["type"]) for c in cols}
        col_list = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(f":{c}" for c in cols)
        insert_sql = text(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})')

        with src_engine.connect() as sconn, pg_engine.begin() as pconn:
            pconn.execute(text(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE'))
            result = sconn.execute(text(f'SELECT {col_list} FROM "{table}"'))
            n = 0
            while True:
                rows = result.fetchmany(batch)
                if not rows:
                    break
                payload = []
                for row in rows:
                    item = {}
                    for c, v in zip(cols, row):
                        item[c] = _coerce(v, type_map[c])
                    payload.append(item)
                pconn.execute(insert_sql, payload)
                n += len(rows)
                if n % 5000 == 0:
                    print(f"  {table}: {n}…")
        summary.append((table, n))
        print(f"OK {table}: {n}")

    with pg_engine.connect() as conn:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        for table in tables:
            pk_cols = pg_insp.get_pk_constraint(table).get("constrained_columns") or []
            if pk_cols != ["id"]:
                continue
            try:
                conn.execute(
                    text(
                        f"""
                        SELECT setval(
                          pg_get_serial_sequence('"{table}"', 'id'),
                          COALESCE((SELECT MAX(id) FROM "{table}"), 1),
                          true
                        )
                        """
                    )
                )
            except Exception as exc:
                print("seq skip", table, exc)
        conn.commit()

    print("---")
    for t, n in summary:
        print(f"{t}\t{n}")
    print("DONE", len(summary), "tables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
