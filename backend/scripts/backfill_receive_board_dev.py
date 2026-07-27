#!/usr/bin/env python3
"""开发库专用：按月回填菲利斯/恩玖收货事件（自 history_start 至今天）。

只写 ems.dev.db。恩玖全量导出走大区间易超时，故按月切片。

用法（在 backend 目录）:
  EMS_DB=ems.dev.db EMS_DEV_MODE=1 .venv/bin/python scripts/backfill_receive_board_dev.py
"""
from __future__ import annotations

import asyncio
import calendar
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

db_name = (os.environ.get("EMS_DB") or "").strip() or "ems.dev.db"
if db_name in ("ems.db", "ems_prod") or db_name.endswith("/ems.db"):
    print("拒绝：本脚本只能写开发库 ems.dev.db，不能碰生产库", file=sys.stderr)
    sys.exit(2)
os.environ["EMS_DB"] = db_name
os.environ.setdefault("EMS_DEV_MODE", "1")
os.environ.pop("DATABASE_URL", None)
os.environ["EMS_USE_SQLITE"] = "1"


def _month_slices(start: date, end: date) -> list[tuple[str, str]]:
    slices: list[tuple[str, str]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first = date(y, m, 1)
        last = date(y, m, calendar.monthrange(y, m)[1])
        if first < start:
            first = start
        if last > end:
            last = end
        slices.append((first.isoformat(), last.isoformat()))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return slices


async def main() -> None:
    from database import SessionLocal
    from receive_events import (
        board_history_start,
        sync_enjiu_delivery_events,
        sync_feilisi_asn_events,
    )
    from receive_snapshot import today_shanghai

    start = board_history_start()
    end = today_shanghai()
    slices = _month_slices(start, end)
    print(f"开发库={db_name} 按月回填 {start} ~ {end}（共 {len(slices)} 段）")

    totals = {"feilisi": 0, "enjiu": 0}
    for date_from, date_to in slices:
        db = SessionLocal()
        try:
            print(f"  菲利斯 {date_from}~{date_to} …", flush=True)
            try:
                n = await sync_feilisi_asn_events(db, date_from=date_from, date_to=date_to)
                totals["feilisi"] += n
                print(f"    -> {n} 行")
            except Exception as exc:
                print(f"    !! 失败: {exc}")
            print(f"  恩玖   {date_from}~{date_to} …", flush=True)
            try:
                n = await sync_enjiu_delivery_events(db, date_from=date_from, date_to=date_to)
                totals["enjiu"] += n
                print(f"    -> {n} 行")
            except Exception as exc:
                print(f"    !! 失败: {exc}")
        finally:
            db.close()

    print(
        "完成:",
        f"feilisi={totals['feilisi']}",
        f"enjiu={totals['enjiu']}",
        f"total={totals['feilisi'] + totals['enjiu']}",
    )


if __name__ == "__main__":
    asyncio.run(main())
