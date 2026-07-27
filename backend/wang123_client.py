"""旧站 wang123.online（zym API）包装数据客户端。"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import ssl

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://zym.wang123.online"
DEFAULT_WEB_BASE = "https://www.wang123.online"
TOKEN_PATH = Path(__file__).resolve().parent / "data" / "wang123_token.txt"


def _ssl():
    return ssl.create_default_context()


class Wang123Client:
    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        username: str = "blue",
        password: str = "blue1",
        token: str = "",
        timeout: int = 120,
    ):
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.username = username
        self.password = password
        self.token = (token or "").strip()
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        auth: bool = True,
    ) -> dict:
        headers = {
            "User-Agent": "EMS-Wang123Sync/1.0",
            "Accept": "application/json",
        }
        url = self.api_base + path
        if params:
            url += "?" + urlencode(params, doseq=True)
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json;charset=utf-8"
        if auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = Request(url, data=body, headers=headers, method=method)
        with urlopen(req, context=_ssl(), timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw or "{}")

    def fetch_captcha(self) -> dict:
        """返回 {uuid, img_svg, captcha_enabled}。"""
        d = self._request("GET", "/captchaImage", auth=False)
        data = d.get("data") or d
        return {
            "uuid": data.get("uuid") or "",
            "img": data.get("img") or "",
            "captcha_enabled": bool(data.get("captchaEnabled", True)),
            "raw": d,
        }

    def login_with_code(self, code: str, uuid: str) -> str:
        d = self._request(
            "POST",
            "/login",
            data={
                "userName": self.username,
                "password": self.password,
                "code": str(code or "").strip(),
                "uuid": str(uuid or "").strip(),
            },
            auth=False,
        )
        token = d.get("token")
        if not token and isinstance(d.get("data"), dict):
            token = d["data"].get("token")
        # 部分版本 code=200 才成功；也兼容 msg=登录成功
        ok = d.get("code") == 200 or bool(token)
        if not ok or not token:
            raise RuntimeError(d.get("msg") or "登录失败")
        self.token = token
        self.save_token()
        return self.token

    def ensure_token(self) -> str:
        if self.token:
            try:
                d = self._request("GET", "/getInfo")
                if d.get("code") == 200:
                    return self.token
            except Exception:
                pass
        # 尝试磁盘缓存
        cached = self.load_token()
        if cached:
            self.token = cached
            try:
                d = self._request("GET", "/getInfo")
                if d.get("code") == 200:
                    return self.token
            except Exception:
                pass
        raise RuntimeError("旧站登录已失效，请先完成验证码登录")

    def save_token(self) -> None:
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(self.token or "", encoding="utf-8")

    @staticmethod
    def load_token() -> str:
        try:
            return TOKEN_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def list_packaged_page(
        self,
        page_num: int = 1,
        page_size: int = 200,
        *,
        package_status: int = 1,
    ) -> dict:
        """已包装列表。package_status=1 为已包装。"""
        self.ensure_token()
        d = self._request(
            "GET",
            "/testdata/list",
            params={
                "pageNum": page_num,
                "pageSize": page_size,
                "packageStatus": package_status,
            },
        )
        if d.get("code") != 200:
            raise RuntimeError(d.get("msg") or "拉取包装列表失败")
        data = d.get("data") or {}
        return {
            "list": data.get("list") or data.get("rows") or [],
            "total": int(data.get("total") or 0),
        }

    def iter_all_packaged(
        self,
        *,
        page_size: int = 200,
        max_pages: int = 0,
        sleep_sec: float = 0.15,
    ):
        first = self.list_packaged_page(1, page_size)
        total = first["total"]
        yield from first["list"]
        pages = max(1, (total + page_size - 1) // page_size)
        if max_pages > 0:
            pages = min(pages, max_pages)
        for page in range(2, pages + 1):
            if sleep_sec:
                time.sleep(sleep_sec)
            for attempt in range(3):
                try:
                    chunk = self.list_packaged_page(page, page_size)
                    yield from chunk["list"]
                    break
                except Exception as exc:
                    logger.warning("wang123 page %s fail %s: %s", page, attempt, exc)
                    time.sleep(1.5 * (attempt + 1))
            else:
                raise RuntimeError(f"拉取第 {page} 页失败")


def solve_math_captcha_from_svg(img_svg: str) -> Optional[str]:
    """尽力从验证码图解出算式结果；失败返回 None（依赖本机 qlmanage）。"""
    if not img_svg:
        return None
    tmp = Path("/tmp/ems_wang123_captcha.svg")
    png = Path("/tmp/ems_wang123_captcha.svg.png")
    try:
        tmp.write_text(img_svg, encoding="utf-8")
        subprocess.run(
            ["qlmanage", "-t", "-s", "800", "-o", "/tmp", str(tmp)],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if not png.is_file():
            return None
        # 可选：若以后装了 OCR 再扩展；当前返回 None 走人工/接口传 code
        return None
    except Exception:
        return None


def parse_math_text(text: str) -> Optional[str]:
    m = re.search(r"(\d+)\s*([+\-xX×*])\s*(\d+)", text or "")
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    if op in "+|":
        return str(a + b)
    if op == "-":
        return str(a - b)
    return str(a * b)
