import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from order_retention import parse_order_date, retention_cutoff_str

logger = logging.getLogger(__name__)

DETAIL_QUERY_DEFAULT = {
    "fuzzyQuery": "",
    "datetimeS": "",
    "datetimeE": "",
    "itemNoLike": "",
    "site": "",
    "PurchaseType": "",
    "replyPurchaseOpinions": "",
    "itemFeatureNo": "",
    "purchaseDeliveryDateS": "",
    "purchaseDeliveryDateE": "",
    "itemName": "",
    "itemSpec": "",
    "orderBy": "[]",
}


class SrmClientV2:
    """智联云采 SRM 2.0（adpweb）"""

    def __init__(self, customer: dict):
        self.customer = customer
        self.base_url = customer["srm_base_url"].rstrip("/")
        self.api_prefix = (customer.get("api_path") or "/adpweb").rstrip("/")
        self.login_name = (customer.get("login_name") or "").strip()
        self.password = customer.get("password") or ""
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    def _api_url(self, path: str) -> str:
        return f"{self.base_url}{self.api_prefix}/{path.lstrip('/')}"

    def _base_headers(self) -> Dict[str, str]:
        headers = {
            "Accept-Language": "zh-CN",
            "Referer": f"{self.base_url}/",
        }
        if self._token:
            headers["Authorization"] = self._token
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0, headers=self._base_headers())
        elif self._token:
            self._client.headers.update({"Authorization": self._token})
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def login(self) -> str:
        client = await self._get_client()
        resp = await client.post(
            self._api_url("api/srm/login"),
            data={
                "vKey": "",
                "vCode": "",
                "loginName": self.login_name,
                "password": self.password,
                "lang": "zh-CN",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        head = data.get("head") or {}
        if head.get("status") != 1:
            raise RuntimeError(head.get("errorMsg") or "SRM 2.0 登录失败")
        body_data = data.get("body") or {}
        token = body_data.get("token")
        if not token:
            raise RuntimeError("SRM 2.0 登录未返回 token")
        self._token = token
        client.headers.update({"Authorization": token})
        return token

    async def _request_json(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        if not self._token:
            await self.login()
        client = await self._get_client()
        resp = await client.request(method, self._api_url(path), json=payload or {})
        resp.raise_for_status()
        data = resp.json()
        head = data.get("head") or {}
        if head.get("errorCode") == "0001":
            await self.login()
            return await self._request_json(method, path, payload)
        if head.get("status") != 1:
            raise RuntimeError(head.get("errorMsg") or f"{path} 请求失败")
        return data.get("body")

    async def fetch_body_detail_list(
        self, closed: bool = False, page_size: int = 2000, date_from: Optional[str] = None
    ) -> List[dict]:
        path = (
            "api/srm/purchase/purchaseBodyCloseListDetail"
            if closed
            else "api/srm/purchase/purchaseBodyListDetail"
        )
        payload = {
            **DETAIL_QUERY_DEFAULT,
            "datetimeS": date_from or "",
            "datetimeE": "",
            "pageNumber": "1",
            "pageSize": str(page_size),
        }
        if not closed:
            payload["overDue"] = "N"
        body = await self._request_json("POST", path, payload)
        lines = body.get("listdata") or []
        if date_from:
            cutoff = parse_order_date(date_from)
            if cutoff:
                lines = [
                    line
                    for line in lines
                    if not parse_order_date(line.get("purchaseDate")) or parse_order_date(line.get("purchaseDate")) >= cutoff
                ]
        return lines

    async def fetch_all_order_lines(self, concurrency: int = 6, date_from: Optional[str] = None) -> Tuple[List[dict], int]:
        await self.login()
        date_from = date_from or retention_cutoff_str()
        results: List[dict] = []
        active_lines = await self.fetch_body_detail_list(closed=False, date_from=date_from)
        for line in active_lines:
            results.append({"head": {}, "line": line, "closed": False})
        logger.info("恩玖进行中订单行: %s", len(active_lines))
        return results, len(active_lines)

    async def get_live_workorder_total(self, date_from: Optional[str] = None) -> int:
        _, total = await self.fetch_all_order_lines(date_from=date_from)
        return total
