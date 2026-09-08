#!/bin/bash
cd /Users/dx/EMS/backend
export PATH="/Users/dx/EMS/backend/.venv/bin:$PATH"
LOG=/tmp/ems-uvicorn.log
# ensure share mounted (Desktop path used by config)
SHARE="/Users/dx/Desktop/共享-测试软件资料"
if [ ! -d "$SHARE/D-仓库表格" ]; then
  mkdir -p "$SHARE"
  mount_smbfs '//guest:@192.168.2.11/%E6%B5%8B%E8%AF%95%E8%BD%AF%E4%BB%B6%E8%B5%84%E6%96%99' "$SHARE" >>"$LOG" 2>&1 || true
fi
# free port if stale
lsof -tiTCP:8000 -sTCP:LISTEN | xargs kill 2>/dev/null || true
sleep 1
echo "$(date '+%F %T') start via Terminal" >>"$LOG"
exec .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 >>"$LOG" 2>&1
