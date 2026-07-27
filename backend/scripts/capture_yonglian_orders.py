#!/usr/bin/env python3
"""永联 SCP 录包：Python 登录 + Playwright 导航采购订单。"""

import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kingdee_client import KingdeeScpClient

BASE = "http://k3.szwinline.com:8880"
API = "/k3cloud"
OUT = Path(__file__).resolve().parent.parent / "yonglian_capture.json"

CUSTOMER = {
    "srm_base_url": BASE,
    "api_path": API,
    "acct_id": "5d6dce3c732bc4",
    "login_name": "07.01.0089",
    "password": "DX123456**",
    "entry_role": "SRM",
}

INTERESTING = re.compile(
    r"(DynamicFormService|ListService|GetEntryData|GetListData|LoadListData|"
    r"GetDynamicFormConfig|SCP_PurchaseOrder|dform\.aspx)",
    re.I,
)


async def python_login():
    client = KingdeeScpClient(CUSTOMER)
    await client.login()
    await client._bootstrap_main_form()
    httpx_client = await client._get_client()
    cookies = []
    for c in httpx_client.cookies.jar:
        cookies.append(
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain or "k3.szwinline.com",
                "path": c.path or "/",
            }
        )
    info = {
        "user_token": client._user_token,
        "main_page_id": client._main_page_id,
        "session_ids": client._session_ids,
        "cookies": cookies,
    }
    await client.close()
    return info


def main() -> int:
    info = asyncio.run(python_login())
    print("login ok page_id=", info["main_page_id"])

    captured = []

    def on_request(req):
        blob = (req.url or "") + (req.post_data or "")
        if not INTERESTING.search(blob):
            return
        entry = {
            "method": req.method,
            "url": req.url,
            "headers": {k: v for k, v in req.headers.items() if k.lower() in (
                "csrf-token", "content-type", "theme", "cookie"
            )},
            "post_data": req.post_data,
        }
        captured.append(entry)
        short = req.url.split("/")[-1][:100]
        print(f">> {req.method} {short}")

    def on_response(resp):
        req = resp.request
        blob = (req.url or "") + (req.post_data or "")
        if not INTERESTING.search(blob):
            return
        try:
            body = resp.text()[:6000]
        except Exception:
            body = "<binary>"
        for e in reversed(captured):
            if e["url"] == req.url and "response" not in e:
                e["status"] = resp.status
                e["response"] = body
                break

    page_id = info["main_page_id"]
    main_url = (
        f"{BASE}{API}/html5/index.aspx?entryrole=SRM"
        f"&formId=SRM_MainControl&pageId={page_id}"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        if info["cookies"]:
            context.add_cookies(info["cookies"])
        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        page.goto(main_url, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(5000)
        print("url after main:", page.url)
        page.screenshot(path=str(OUT.with_suffix(".main.png")), full_page=True)

        # 菜单点击
        clicked = False
        for text in ["采购订单", "采购管理", "订单协同", "我的订单"]:
            try:
                loc = page.get_by_text(text, exact=False)
                if loc.count() > 0:
                    loc.first.click(timeout=8000)
                    page.wait_for_timeout(8000)
                    print("clicked:", text)
                    clicked = True
                    break
            except Exception as exc:
                print("click fail", text, exc)

        if not clicked:
            # 尝试 iframe 内菜单
            for frame in page.frames:
                for text in ["采购订单", "采购管理"]:
                    try:
                        loc = frame.get_by_text(text, exact=False)
                        if loc.count():
                            loc.first.click(timeout=5000)
                            page.wait_for_timeout(8000)
                            print("clicked in frame:", text)
                            clicked = True
                            break
                    except Exception:
                        pass
                if clicked:
                    break

        page.wait_for_timeout(10000)
        print("final url:", page.url)
        page.screenshot(path=str(OUT.with_suffix(".final.png")), full_page=True)
        browser.close()

    payload = {"session": {k: info[k] for k in ("main_page_id", "session_ids")}, "requests": captured}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(captured)} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
