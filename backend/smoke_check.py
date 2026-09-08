#!/usr/bin/env python3
"""EMS 全模块只读冒烟检查。用法：.venv/bin/python smoke_check.py [base_url]"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
USER = "planner"
PASSWORD = "888888"

# name, method, path — 路径按当前 routers 实际挂载
ENDPOINTS = [
    ("首页", "GET", "/"),
    ("登录态", "GET", "/api/auth/status"),
    ("看板统计", "GET", "/api/dashboard/stats"),
    ("看板最近订单", "GET", "/api/dashboard/recent-orders"),
    ("订单列表", "GET", "/api/orders?page=1&page_size=5&completed=all&receive_filter=all&controlled=all"),
    ("订单计数", "GET", "/api/orders/count?completed=all&receive_filter=all&controlled=all"),
    ("新订单", "GET", "/api/orders/new-orders?limit=1"),
    ("订单状态选项", "GET", "/api/orders/status-options"),
    ("同步客户", "GET", "/api/sync/customers"),
    ("同步通知", "GET", "/api/sync/notifications?after_log_id=0"),
    ("仓库配置", "GET", "/api/warehouse/config"),
    ("仓库客户", "GET", "/api/warehouse/customers"),
    ("物料明细", "GET", "/api/warehouse/materials?keyword=03039026"),
    ("机型用料", "GET", "/api/warehouse/materials/by-model?model_code=03039026&order_qty=1"),
    ("工程配置", "GET", "/api/engineering/config"),
    ("工程待审数", "GET", "/api/engineering/review-inbox/count"),
    ("工程待办A123", "GET", "/api/engineering/todos?internal_code=A123"),
    ("工程待办A120", "GET", "/api/engineering/todos?internal_code=A120"),
    ("工程机型A123", "GET", "/api/engineering/models?internal_code=A123"),
    ("排产列表", "GET", "/api/scheduling"),
    ("排产元数据", "GET", "/api/scheduling/meta"),
    ("物料管制", "GET", "/api/material-controls"),
    ("报价列表", "GET", "/api/quotation"),
    ("人事员工", "GET", "/api/hr/employees?page=1&page_size=5"),
    ("人事元数据", "GET", "/api/hr/employees/meta"),
    ("镭雕批次", "GET", "/api/laser/batches"),
    ("工序工位", "GET", "/api/process-scan/stations"),
]


def _req(method: str, path: str, token: str | None = None, body: dict | None = None, timeout: float = 25.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Auth-Token"] = token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            detail = ""
            try:
                parsed = json.loads(raw.decode("utf-8") or "{}")
                if isinstance(parsed, dict) and "detail" in parsed:
                    detail = str(parsed["detail"])[:160]
            except Exception:
                detail = raw[:120].decode("utf-8", errors="ignore")
            return resp.status, detail, raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            detail = str(payload.get("detail") or "")[:160]
        except Exception:
            detail = str(e.reason)
        return e.code, detail, raw
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", b""


def main() -> int:
    print(f"冒烟检查 → {BASE}")
    code, detail, raw = _req("POST", "/api/auth/login", body={"username": USER, "password": PASSWORD})
    if code != 200:
        print(f"FAIL 登录 {code} {detail}")
        return 2
    try:
        login = json.loads(raw.decode("utf-8"))
    except Exception:
        print("FAIL 登录响应非 JSON")
        return 2
    token = login.get("token") or ""
    if not token:
        print("FAIL 登录成功但无 token", login)
        return 2
    print(f"OK  登录 ({USER} / {login.get('role')})")

    bad = []
    soft_n = 0
    for name, method, path in ENDPOINTS:
        use_token = token if path.startswith("/api/") else None
        status, detail, _ = _req(method, path, token=use_token)
        ok = status in (200, 204)
        soft = status in (401, 403, 404)
        if ok:
            mark = "OK "
        elif soft:
            mark = "SOFT"
            soft_n += 1
        else:
            mark = "FAIL"
            bad.append((name, status, path, detail))
        print(f"{mark} {status:3d} {name:12s} {path}{('  ' + detail) if (not ok) else ''}")

    print("---")
    if bad:
        print(f"失败 {len(bad)} 项（Soft={soft_n}）：")
        for item in bad:
            print(" ", item)
        return 1
    print(f"全部关键接口正常（含 Soft 权限拒绝 {soft_n} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
