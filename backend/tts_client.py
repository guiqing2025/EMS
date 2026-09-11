"""TTS（生产管理品质信息追溯系统）API 客户端。

登录页：http://tts.felicitysolar.com:8081/login
业务 API：http://tts.felicitysolar.com:8890
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from config import load_config

logger = logging.getLogger(__name__)

DEFAULT_TTS = {
    "api_base": "http://tts.felicitysolar.com:8890",
    "username": "dx0101",
    "password": "123456",
    "customer_id": "feilisi",
    "customer_name": "客户A",
    "auto_sync_enabled": False,
    "sync_interval_minutes": 60,
    "max_workers": 8,
}


def tts_cfg() -> dict:
    cfg = load_config().get("tts") or {}
    out = {**DEFAULT_TTS, **cfg}
    out["api_base"] = str(out.get("api_base") or DEFAULT_TTS["api_base"]).rstrip("/")
    return out


class TtsClient:
    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = cfg or tts_cfg()
        self.base = self.cfg["api_base"]
        self.token: Optional[str] = None

    def login(self) -> str:
        payload = {
            "userName": self.cfg.get("username") or DEFAULT_TTS["username"],
            "password": self.cfg.get("password") or DEFAULT_TTS["password"],
        }
        data = self._request("POST", "/userlogin", payload, auth=False)
        if not isinstance(data, dict) or data.get("code") != 200:
            raise RuntimeError(f"TTS 登录失败：{(data or {}).get('message') or data}")
        token = (data.get("data") or {}).get("token")
        if not token:
            raise RuntimeError("TTS 登录成功但未返回 token")
        self.token = token
        return token

    def ensure_login(self) -> None:
        if not self.token:
            self.login()

    def list_outsource_orders(self, *, page_size: int = 100) -> list[str]:
        """拉取全部委外/采购单号。"""
        self.ensure_login()
        out: list[str] = []
        page = 1
        while page <= 200:
            data = self._request(
                "POST",
                "/semiProductProduceOrder/list_outsource_order",
                {"pageNum": page, "pageSize": page_size},
            )
            if not isinstance(data, dict) or data.get("code") != 200:
                raise RuntimeError(f"拉取委外单失败：{(data or {}).get('message') or data}")
            body = data.get("data") or {}
            rows = body.get("dataList") or []
            out.extend(str(x).strip() for x in rows if str(x).strip())
            total_page = int(body.get("totalPage") or 1)
            if page >= total_page or not rows:
                break
            page += 1
        # 去重保序
        seen = set()
        uniq = []
        for po in out:
            if po in seen:
                continue
            seen.add(po)
            uniq.append(po)
        return uniq

    def list_order_histories(self, purchase_no: str) -> list[dict[str, Any]]:
        """某采购单下的 PCBA 流水号登记（含镭雕段与补码）。"""
        self.ensure_login()
        po = (purchase_no or "").strip()
        if not po:
            return []
        data = self._request(
            "POST",
            "/semiProductProduceOrder/list_outsource_order_details",
            {"outsourceOrder": po, "pageNum": 1, "pageSize": 200},
        )
        if not isinstance(data, dict) or data.get("code") != 200:
            # 个别单可能空指针，跳过
            logger.warning("TTS 明细失败 %s：%s", po, (data or {}).get("message") or data)
            return []
        rows: list[dict] = []
        for block in (data.get("data") or {}).get("dataList") or []:
            for h in block.get("semiProductOrderHistoryVOS") or []:
                if isinstance(h, dict):
                    rows.append(h)
        return rows

    def iter_all_histories(self, *, max_workers: Optional[int] = None) -> list[dict[str, Any]]:
        """并发拉取全部委外单的流水号登记。"""
        orders = self.list_outsource_orders()
        workers = int(max_workers or self.cfg.get("max_workers") or 8)
        workers = max(1, min(16, workers))
        all_rows: list[dict] = []
        errors = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(self.list_order_histories, po): po for po in orders}
            for fut in as_completed(futs):
                po = futs[fut]
                try:
                    all_rows.extend(fut.result())
                except Exception:
                    errors += 1
                    logger.exception("TTS 拉取明细异常 %s", po)
        logger.info("TTS 流水登记：订单 %s，记录 %s，失败 %s", len(orders), len(all_rows), errors)
        return all_rows

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        *,
        auth: bool = True,
        timeout: int = 60,
    ) -> Any:
        url = f"{self.base}{path if path.startswith('/') else '/' + path}"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if auth:
            if not self.token:
                raise RuntimeError("TTS 未登录")
            headers["Authorization"] = self.token
        raw = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=raw, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                return json.loads(text)
            except Exception:
                return {"code": e.code, "message": text[:300]}
