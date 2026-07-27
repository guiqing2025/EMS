import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from order_retention import parse_order_date, retention_cutoff_str

logger = logging.getLogger(__name__)

COMPLETED_STATUS_NAMES = {"已结案", "指定结案", "已收货", "已完成"}
INCOMPLETE_STATUS_NAMES = {"待确认", "受理中", "已受理", "交货中", "已确认", "待发货"}


def make_line_key(
    customer_id: str,
    purchase_no: str,
    purchase_seq: str,
    purchase_phase_seq: str,
) -> str:
    return f"{customer_id}|{purchase_no.strip()}|{purchase_seq or '0'}|{purchase_phase_seq or '0'}"


class SrmClient:
    def __init__(self, customer: dict):
        self.customer = customer
        self.customer_id = customer["id"]
        self.customer_name = customer.get("name") or customer["id"]
        self.base_url = customer["srm_base_url"].rstrip("/")
        self.login_name = customer["login_name"]
        self.password = customer["password"]
        self._token: Optional[str] = None

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept-Language": "zh-CN"}
        if self._token:
            headers["Authentication-Info"] = self._token
        return headers

    async def login(self) -> str:
        pwd_md5 = hashlib.md5(self.password.encode()).hexdigest()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/ilcsrmdata/loginByUserName",
                json={"loginName": self.login_name, "password": pwd_md5},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != "000001":
            raise RuntimeError(data.get("msg", "SRM 登录失败"))
        self._token = data["data"]["token"]
        return self._token

    async def _post(self, path: str, payload: Optional[dict] = None, base: str = "/ilcsrmpurchase") -> Any:
        if not self._token:
            await self.login()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}{base}{path}",
                json=payload or {},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") == "000701":
            await self.login()
            return await self._post(path, payload, base)
        if data.get("code") != "000001":
            raise RuntimeError(f"{path}: {data.get('msg', '请求失败')}")
        return data.get("data")

    async def fetch_workorders_page(
        self, current: int = 1, size: int = 100, date_from: Optional[str] = None
    ) -> dict:
        condition: Dict[str, Any] = {}
        if date_from:
            condition["docDateStart"] = date_from
        return await self._post(
            "/srmPurWorkorder/getWorkorderHead",
            {"current": current, "size": size, "condition": condition, "field": "docDate", "order": "desc"},
        )

    async def fetch_purchase_head(self, purchase_no: str) -> dict:
        return await self._post("/srmPurHead/getPurchaseHead", {"purchaseNo": purchase_no})

    async def fetch_purchase_body_lines(self, purchase_no: str) -> List[dict]:
        data = await self._post(
            "/srmProductionReportHead/getPurchaseBodyByPurNo",
            {"purchaseNo": purchase_no},
        )
        return data if isinstance(data, list) else []

    async def fetch_all_workorders(self, date_from: Optional[str] = None) -> List[dict]:
        await self.login()
        cutoff = parse_order_date(date_from) if date_from else None
        all_records: List[dict] = []
        current = 1
        while True:
            page = await self.fetch_workorders_page(current=current, size=100, date_from=date_from)
            records = page.get("records") or []
            if cutoff:
                kept = []
                stop = False
                for wo in records:
                    doc = parse_order_date(wo.get("docDate"))
                    if doc and doc < cutoff:
                        stop = True
                        break
                    kept.append(wo)
                all_records.extend(kept)
                if stop or not records:
                    break
            else:
                all_records.extend(records)
            total = page.get("total") or 0
            if len(all_records) >= total or not records:
                break
            current += 1
        return all_records

    async def _fetch_body_safe(self, purchase_no: str, retries: int = 5) -> Tuple[str, List[dict]]:
        last_exc = None
        for attempt in range(retries):
            try:
                lines = await self.fetch_purchase_body_lines(purchase_no)
                if lines:
                    return purchase_no, lines
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                logger.warning("获取订单行 %s 失败(第%s次): %s", purchase_no, attempt + 1, exc)
                if attempt < retries - 1:
                    delay = 1.2 * (attempt + 1) if "请勿重复请求" in msg else 0.4 * (attempt + 1)
                    await asyncio.sleep(delay)
                    continue
            if attempt < retries - 1:
                await asyncio.sleep(0.4 * (attempt + 1))
        if last_exc:
            logger.warning("订单 %s 明细最终获取失败", purchase_no)
        return purchase_no, []

    async def fetch_asn_outsource_pur_detail_page(
        self, current: int = 1, size: int = 200
    ) -> dict:
        """ASN 跟踪 → 新增 ASN → 订单性质「委外订单」可选采购明细。"""
        return await self._post(
            "/srmAsn/getAsnPurDetailPage",
            {
                "current": current,
                "size": size,
                "condition": {"orderType": "2"},  # 2 = 委外订单
            },
        )

    async def fetch_all_asn_outsource_pur_lines(self) -> Tuple[List[dict], int]:
        """拉取 ASN 新增页中委外在制订单明细，返回 (行列表, 行数)。"""
        await self.login()
        all_records: List[dict] = []
        current = 1
        size = 200
        total = None
        while True:
            page = await self.fetch_asn_outsource_pur_detail_page(current=current, size=size)
            records = page.get("records") or []
            if total is None:
                total = int(page.get("total") or 0)
            all_records.extend(records)
            if not records:
                break
            if total and len(all_records) >= total:
                break
            if len(records) < size:
                break
            current += 1
        # 按采购单号+项次去重，保留首次出现
        seen = set()
        unique: List[dict] = []
        for row in all_records:
            key = (
                str(row.get("purchaseNo") or "").strip(),
                str(row.get("purchaseSeq") or "0").strip(),
                str(row.get("purchasePhaseSeq") or "0").strip(),
                str(row.get("purchaseBatchSeq") or "0").strip(),
            )
            if not key[0] or key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique, len(unique)

    async def fetch_all_order_lines(
        self, concurrency: int = 2, date_from: Optional[str] = None
    ) -> Tuple[List[dict], int]:
        """菲利斯在制订单：与 ASN「新增 ASN / 委外订单」列表同源。"""
        del concurrency, date_from  # 兼容旧调用签名
        lines, total = await self.fetch_all_asn_outsource_pur_lines()
        return [{"asn_line": line} for line in lines], total

    async def fetch_reconciliation_page(self, current: int = 1, size: int = 100) -> dict:
        data = await self._post(
            "/srmInvoice/getInvoiceHeadPage",
            {"current": current, "size": size, "condition": {}},
        )
        return data if isinstance(data, dict) else {"records": [], "total": 0}

    async def fetch_all_reconciliation(self) -> List[dict]:
        all_records: List[dict] = []
        current = 1
        while True:
            page = await self.fetch_reconciliation_page(current=current, size=100)
            records = page.get("records") or []
            all_records.extend(records)
            total = page.get("total") or 0
            if len(all_records) >= total or not records:
                break
            current += 1
        return all_records

    async def fetch_asn_body_page(
        self,
        current: int = 1,
        size: int = 200,
        *,
        delivery_date_start: Optional[str] = None,
        delivery_date_end: Optional[str] = None,
        asn_no: Optional[str] = None,
        order_type: str = "2",
    ) -> dict:
        condition: Dict[str, Any] = {}
        if order_type:
            condition["orderType"] = order_type
        if delivery_date_start:
            condition["deliveryDateStart"] = delivery_date_start
        if delivery_date_end:
            condition["deliveryDateEnd"] = delivery_date_end
        if asn_no:
            condition["asnNo"] = asn_no
        data = await self._post(
            "/srmAsn/getAsnBodyPage",
            {"current": current, "size": size, "condition": condition},
        )
        return data if isinstance(data, dict) else {"records": [], "total": 0}

    async def fetch_all_asn_body_lines(
        self,
        *,
        delivery_date_start: str,
        delivery_date_end: str,
        order_type: str = "2",
    ) -> List[dict]:
        """按送货/收货日拉取 ASN 行明细（含 receiveQty / goodsNo）。"""
        await self.login()
        all_records: List[dict] = []
        current = 1
        size = 200
        while True:
            page = await self.fetch_asn_body_page(
                current=current,
                size=size,
                delivery_date_start=delivery_date_start,
                delivery_date_end=delivery_date_end,
                order_type=order_type,
            )
            records = page.get("records") or []
            all_records.extend(records)
            total = int(page.get("total") or 0)
            if not records:
                break
            if total and len(all_records) >= total:
                break
            if len(records) < size:
                break
            current += 1
        return all_records

    async def get_live_workorder_total(self, date_from: Optional[str] = None) -> int:
        del date_from
        _, total = await self.fetch_all_asn_outsource_pur_lines()
        return total

    async def fetch_active_status_map(self) -> dict:
        return {}


def _normalize_seq(value, *, width: Optional[int] = None) -> str:
    text = str(value if value is not None else "0").strip() or "0"
    if text.isdigit():
        num = str(int(text))
        if width:
            return num.zfill(width)
        return num
    return text


def is_line_completed(line: dict) -> bool:
    name = (line.get("statusName") or "").strip()
    if name in COMPLETED_STATUS_NAMES:
        return True
    if name in INCOMPLETE_STATUS_NAMES:
        return False
    undel = float(line.get("unDeliveryQty") or 0)
    unrecv = float(line.get("unReceiveQty") or 0)
    batch = float(line.get("batchPurQty") or 0)
    if batch > 0:
        return undel <= 0 and unrecv <= 0
    return True
