"""金蝶云星空 SCP（供应商协同）客户端。"""

import base64
import gzip
import json
import logging
import random
import re
import string
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from order_retention import retention_cutoff_str

logger = logging.getLogger(__name__)

SCP_PURCHASE_FORM = "SCP_PurchaseOrder"
# 采购端列表（同账号可开）：含 FTaxPrice / FAllAmount；SCP 供应商列表通常不含金额列
PUR_PURCHASE_FORM = "PUR_PurchaseOrder"
LIST_GRID_KEY = "FLIST"
# 永联侧供应商名称匹配（PUR 列表为全供应商，需客户端过滤）
YONGLIAN_SUPPLIER_KEYWORDS = ("鼎雄",)


def _cell_value(value: Any) -> Any:
    if isinstance(value, list) and value:
        for item in reversed(value):
            if item is None:
                continue
            if isinstance(item, (int, float)):
                return item
            text = str(item).strip()
            if text and text != " ":
                return text
        return value[0]
    if isinstance(value, str):
        return value.strip()
    return value


def _parse_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


try:
    import ddddocr
except ImportError:  # pragma: no cover
    ddddocr = None  # type: ignore


def _encrypt_credentials(username: str, password: str) -> str:
    """对齐浏览器 beforeLogin 加密，写入 CustomizationParameter.a。"""
    payload = {"u": username, "p": password}
    payload["zt"] = "".join(str(random.random()).replace(".", ""))
    payload["rt"] = int(time.time() * 1000)
    payload["cr"] = "".join(str(random.random()).replace(".", ""))
    ordered = {k: payload[k] for k in sorted(payload.keys())}
    raw = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    shift = len(b64) % 95
    out = []
    for ch in b64:
        code = ord(ch) - shift
        if code < 32:
            code += 95
        elif code > 126:
            code -= 95
        out.append(chr(code))
    return base64.b64encode("".join(out).encode("ascii")).decode("ascii")


def _str_char_flag(key: str) -> int:
    flag = 31
    for ch in key or "":
        flag += ord(ch)
    return flag % 126


def _before_trans_form(state: dict) -> str:
    """生成 dform.aspx 所需的 _cnneptstate_ 参数。"""
    raw = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
    encoded = urllib.parse.quote(raw, safe="")
    shift = (_str_char_flag(state.get("key") or "") + len(encoded)) % 95
    out = []
    for ch in encoded:
        code = ord(ch) - shift
        if code < 32:
            code += 95
        elif code > 126:
            code -= 95
        out.append(chr(code))
    return base64.b64encode("".join(out).encode("ascii")).decode("ascii")


def _csrf_token(page_id: str) -> str:
    if not page_id or page_id.lower() == "mainpageid":
        return ""
    scope = page_id.replace("-", "")[:16]
    nonce = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(6))
    raw = f"{nonce}&{scope}&{int(time.time() * 1000)}"
    return base64.b64encode(raw.encode("ascii")).decode("ascii")


def _decode_kingdee_response(text: str) -> Any:
    text = (text or "").strip().strip('"')
    if not text:
        return []
    if text.startswith("response_error"):
        raise RuntimeError(text.split("错误信息：", 1)[-1].strip()[:300])
    if text.startswith("H4sI"):
        text = gzip.decompress(base64.b64decode(text)).decode("utf-8", "replace")
    elif text.startswith("eJy"):
        import zlib

        text = zlib.decompress(base64.b64decode(text), wbits=15).decode("utf-8", "replace")
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    return text


def _pick_error_title(payload: Any) -> Optional[str]:
    if not isinstance(payload, list):
        return None
    for block in payload:
        if not isinstance(block, dict):
            continue
        params = block.get("params") or []
        if params and isinstance(params[0], dict):
            title = params[0].get("errorTitle")
            if title:
                return str(title)
    return None


class KingdeeScpClient:
    def __init__(self, customer: dict):
        self.customer = customer
        self.base_url = customer["srm_base_url"].rstrip("/")
        self.api_prefix = (customer.get("api_path") or "/k3cloud").rstrip("/")
        self.acct_id = (customer.get("acct_id") or "").strip()
        self.login_name = (customer.get("login_name") or "").strip()
        self.password = customer.get("password") or ""
        self.entry_role = (customer.get("entry_role") or "SRM").strip()
        self._client: Optional[httpx.AsyncClient] = None
        self._login_context: Optional[dict] = None
        self._user_token: Optional[str] = None
        self._main_page_id: Optional[str] = None
        self._session_ids: dict = {}

    def _url(self, service: str, method: str) -> str:
        return f"{self.base_url}{self.api_prefix}/{service}.{method}.common.kdsvc"

    def _client_info(self) -> dict:
        return {
            "Version": "HTML5",
            "ClientType": 16,
            "ipAddress": "127.0.0.1",
            "macAddress": "browser",
            "IsDefaultInfo": True,
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _service_post(
        self,
        service: str,
        method: str,
        ap_values: List[Any],
        *,
        scope: Optional[str] = None,
        compressed: bool = False,
    ) -> Any:
        client = await self._get_client()
        url = self._url(service, method)
        payload: Dict[str, Any] = {
            "format": "1",
            "v": "1.0",
            "nonce": "",
            "sign": "",
            "timestamp": json.dumps("2026-01-01T00:00:00.000Z"),
            "compressed": compressed,
            "compressedapx": False,
            "useragent": "KD.HTML5.GZIP",
            "clientinfo": json.dumps(self._client_info()),
            "forminfo": json.dumps({"scope": scope or self.entry_role}),
        }
        for idx, value in enumerate(ap_values):
            payload[f"ap{idx}"] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return _decode_kingdee_response(resp.text)

    async def _ocr_validation_code(self) -> str:
        if ddddocr is None:
            raise RuntimeError("缺少 ddddocr 依赖，无法识别永联登录验证码")
        ocr = ddddocr.DdddOcr(show_ad=False)
        raw = await self._service_post(
            "Kingdee.BOS.ServiceFacade.ServicesStub.Account.AccountService",
            "GetValidationCodeImageByte",
            [self.acct_id],
        )
        if isinstance(raw, str):
            img_b64 = raw.strip().strip('"')
        else:
            img_b64 = str(raw).strip().strip('"')
        return ocr.classification(base64.b64decode(img_b64))

    async def login(self) -> None:
        if not self.acct_id:
            raise RuntimeError("永联账套 ID 未配置（acct_id）")
        client = await self._get_client()
        await client.get(f"{self.base_url}{self.api_prefix}/html5/SCPIndex.aspx")
        await client.get(f"{self.base_url}{self.api_prefix}/html5/index.aspx?entryrole={self.entry_role}")

        last_error = "登录失败"
        for _ in range(20):
            try:
                code = await self._ocr_validation_code()
            except Exception as exc:
                raise RuntimeError(f"永联验证码获取/识别失败: {exc}") from exc

            enc = _encrypt_credentials(self.login_name, self.password)
            login_info = {
                "Username": self.login_name,
                "Password": self.password,
                "AcctID": self.acct_id,
                "Lcid": 2052,
                "AuthenticateType": 1,
                "ValidationCode": code,
                "EncyptType": 1,
                "PasswordIsEncrypted": False,
                "AuthSign": "HTML5",
                "EntryRole": "srm",
                "IsShowLoggedInMessage": False,
                "SMSCode": "",
                "ClientInfo": self._client_info(),
                "CustomizationParameter": json.dumps({"a": enc, "c": ""}),
            }
            result = await self._service_post(
                "Kingdee.BOS.ServiceFacade.ServicesStub.DynamicForm.SRMActionService",
                "ValidateLoginInfo",
                [login_info],
            )
            if not isinstance(result, dict):
                last_error = f"登录返回异常: {result!r}"
                continue
            login_type = result.get("LoginResultType")
            if login_type not in (1, -2):
                last_error = result.get("Message") or "登录失败"
                if "验证码" in last_error:
                    continue
                raise RuntimeError(last_error)

            self._login_context = result.get("Context") or {}
            self._user_token = self._login_context.get("UserToken")
            redirect = result.get("RedirectFormParam") or {}
            self._main_page_id = redirect.get("PageId")
            if not self._user_token or not self._main_page_id:
                raise RuntimeError("永联登录成功但未返回 UserToken/PageId")

            build = await self._service_post(
                "Kingdee.BOS.ServiceFacade.ServicesStub.User.UserService",
                "BuildSessionWithHtml5",
                [self._user_token, self._client_info()],
            )
            if isinstance(build, dict):
                self._session_ids = {
                    "kdservice-sessionid": build.get("KDSVCSessionId"),
                    "aspnet": build.get("ASPNETSessionId"),
                }
            logger.info(
                "永联 SCP 登录成功（%s）",
                result.get("Message") or self._login_context.get("UserName") or self.login_name,
            )
            return

        raise RuntimeError(f"永联登录失败（验证码或凭证错误）: {last_error}")

    def _dform_state(self) -> dict:
        if not self._user_token:
            raise RuntimeError("永联会话未初始化，请先 login()")
        aspnet = self._session_ids.get("aspnet") or ""
        kdsid = self._session_ids.get("kdservice-sessionid") or ""
        return {
            "ut": self._user_token,
            "sid": kdsid,
            "key": aspnet,
            "lcp": {},
        }

    async def _open_list_form(
        self, form_id: str = SCP_PURCHASE_FORM, *, use_main_page_id: bool = True
    ) -> Tuple[str, dict, List[str]]:
        """打开列表 dform，返回 list_page_id、config、列 dataIndex 顺序。"""
        if not self._main_page_id:
            raise RuntimeError("永联会话未初始化，请先 login()")
        client = await self._get_client()
        if not self._session_ids.get("aspnet"):
            for cookie in client.cookies.jar:
                if cookie.name == "ASP.NET_SessionId":
                    self._session_ids["aspnet"] = cookie.value
                    break
        cnnept = _before_trans_form(self._dform_state())
        page_q = f"&pageId={self._main_page_id}" if use_main_page_id else ""
        dform_url = (
            f"{self.base_url}{self.api_prefix}/html5/dform.aspx"
            f"?formId={form_id}&formType=list&entryrole={self.entry_role}"
            f"{page_q}"
            f"&_cnneptstate_={urllib.parse.quote(cnnept)}&custparam="
        )
        resp = await client.get(dform_url)
        resp.raise_for_status()
        match = re.search(r'id="config" type="hidden" value="([^"]+)"', resp.text)
        if not match:
            raise RuntimeError(f"永联列表 dform 未返回配置（{form_id}）")
        import html as html_lib

        cfg = json.loads(html_lib.unescape(match.group(1)))
        if isinstance(cfg, list):
            raise RuntimeError(f"永联打开列表失败（{form_id}）: {cfg!r}"[:300])
        if cfg.get("formid") != form_id:
            raise RuntimeError(
                f"永联列表表单异常: 期望 {form_id}，实际 {cfg.get('formid')}"
            )
        list_page_id = cfg.get("pageId")
        if not list_page_id:
            raise RuntimeError(f"永联列表未返回 pageId（{form_id}）")

        await self._dynamic_form_call(
            form_id,
            "FormMetaDataService",
            "GetListMetadata",
            [],
            csrf_header=True,
        )
        load_data = await self._dynamic_form_call(
            list_page_id,
            "ListService",
            "LoadData",
            {
                "FormId": form_id,
                "StartRow": 0,
                "Limit": 2000,
                "TopRowCount": 0,
            },
            csrf_header=True,
        )
        columns = self._extract_list_columns(load_data)
        return list_page_id, cfg, columns

    @staticmethod
    def _extract_list_columns(load_data: Any) -> List[str]:
        if not isinstance(load_data, list):
            return []
        for block in load_data:
            if not isinstance(block, dict) or block.get("actionname") != "InvokeControlMethod":
                continue
            for param in block.get("params") or []:
                if param.get("methodname") != "CreateDyanmicList":
                    continue
                args = param.get("args") or []
                if not args or not isinstance(args[0], dict):
                    continue
                cols = args[0].get("columns") or []
                return [col.get("dataIndex") for col in cols if col.get("dataIndex")]
        return []

    async def _fetch_entry_rows(self, list_page_id: str, start: int, limit: int) -> dict:
        data = await self._dynamic_form_call(
            list_page_id,
            "ListService",
            "GetEntryData",
            json.dumps([LIST_GRID_KEY, start, limit, None]),
            ap1=list_page_id,
            csrf_header=True,
        )
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return data
        raise RuntimeError(f"永联采购订单 GetEntryData 返回异常: {data!r}")

    @staticmethod
    def _rows_from_entry_payload(rows: List[list], columns: List[str]) -> List[dict]:
        if not rows:
            return []
        if not columns:
            columns = [
                "FBillNo",
                "FDate",
                "FSupplierId.FName",
                "FPurchaseOrgId.FName",
                "FDeliveryDate",
                "FDocumentStatus",
                "FMaterialId.FNumber",
                "FMaterialName",
                "FUnitID.FName",
                "FQty",
                "FJOINQTY",
                "FMRPTerminateStatus",
                "FWWPickMtlQty",
                "FMRPCloseStatus",
                "FID",
                "FPOOrderEntry_FENTRYID",
                "FIDENTITYID",
            ]
        parsed: List[dict] = []
        current_head: dict = {}
        current_bill_no = ""
        line_seq = 0
        for raw in rows:
            if not isinstance(raw, list):
                continue
            item = {
                columns[i]: _cell_value(raw[i]) if i < len(raw) else None
                for i in range(len(columns))
            }
            bill_no = str(item.get("FBillNo") or "").strip()
            if bill_no and bill_no != " ":
                current_bill_no = bill_no
                current_head = {k: v for k, v in item.items() if _cell_value(v) not in (None, "", " ")}
                line_seq = 1
            else:
                line_seq += 1
                if current_bill_no:
                    item["FBillNo"] = current_bill_no
                for key, val in current_head.items():
                    if key not in (
                        "FMaterialId.FNumber",
                        "FMaterialId.FName",
                        "FMaterialName",
                        "FQty",
                        "FJOINQTY",
                        "FMRPCloseStatus",
                        "FIDENTITYID",
                        "FPOOrderEntry_FENTRYID",
                    ):
                        if _cell_value(item.get(key)) in (None, "", " "):
                            item[key] = val
            entry_id = _cell_value(item.get("FPOOrderEntry_FENTRYID"))
            identity_id = _cell_value(item.get("FIDENTITYID"))
            item["FSeq"] = entry_id or line_seq or identity_id
            qty = _parse_number(item.get("FQty"))
            received = _parse_number(item.get("FJOINQTY"))
            item["FReceiveQty"] = received
            item["FRemainReceiveQty"] = max(qty - received, 0.0)
            if str(item.get("FDocumentStatus") or "").strip() in ("已审核",):
                item["FDocumentStatus"] = "C"
            parsed.append(item)
        return parsed

    async def _dynamic_form_call(
        self,
        page_scope: str,
        service: str,
        method: str,
        params: Any,
        *,
        ap1: Optional[str] = None,
        csrf_scope: Optional[str] = None,
        csrf_header: bool = False,
    ) -> Any:
        client = await self._get_client()
        url = self._url(
            "Kingdee.BOS.ServiceFacade.ServicesStub.DynamicForm.DynamicFormService",
            "Call",
        )
        ap3 = params if isinstance(params, str) else json.dumps(params, ensure_ascii=False)
        ap1_val = ap1 or page_scope
        payload: Dict[str, Any] = {
            "format": "1",
            "v": "1.0",
            "nonce": "",
            "sign": "",
            "timestamp": json.dumps("2026-01-01T00:00:00.000Z"),
            "compressed": True,
            "useragent": "KD.HTML5.GZIP",
            "clientinfo": json.dumps(self._client_info()),
            "forminfo": json.dumps({"scope": page_scope}),
            "ap0": service,
            "ap1": ap1_val,
            "ap2": method,
            "ap3": ap3,
        }
        headers = {"Theme": "standard"}
        token = _csrf_token(csrf_scope or ap1_val)
        if csrf_header:
            if token:
                headers["CSRF-Token"] = token
        elif token:
            payload["kdbizenc"] = token

        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = _decode_kingdee_response(resp.text)
        err = _pick_error_title(data)
        if err:
            raise RuntimeError(err)
        return data

    async def fetch_purchase_orders(self, date_from: Optional[str] = None) -> List[dict]:
        date_from = date_from or retention_cutoff_str()
        list_page_id, _cfg, columns = await self._open_list_form(SCP_PURCHASE_FORM)

        payload = await self._fetch_entry_rows(list_page_id, 0, 2000)
        rows = self._rows_from_entry_payload(payload.get("rows") or [], columns)
        if date_from and rows:
            rows = [
                r
                for r in rows
                if str(_cell_value(r.get("FDate")) or "")[:10].replace("/", "-") >= date_from[:10]
            ]
        logger.info("永联 SCP 采购订单拉取 %s 行（list_page=%s）", len(rows), list_page_id)
        return rows

    async def fetch_supplier_purchase_lines(
        self,
        *,
        supplier_keywords: Tuple[str, ...] = YONGLIAN_SUPPLIER_KEYWORDS,
        max_scan: int = 80000,
        page_size: int = 1000,
        date_from: Optional[str] = None,
    ) -> List[dict]:
        """拉取采购端 PUR_PurchaseOrder 中鼎雄全部行（含单价/关闭状态）。

        SCP 供应商列表通常无金额列，结案后也可能从在制列表消失。
        PUR 含 FTaxPrice/FAllAmount；FRemainReceiveQty 在供应商账号下常不可靠
        （恒等于 FQty），结案行（FMRPCloseStatus/FCloseStatus=Y）按已收满处理。
        """
        list_page_id, _cfg, columns = await self._open_list_form(
            PUR_PURCHASE_FORM, use_main_page_id=False
        )
        keywords = tuple(k for k in supplier_keywords if k)
        out: List[dict] = []
        cutoff = (date_from or "")[:10]

        for start in range(0, max_scan, page_size):
            payload = await self._fetch_entry_rows(list_page_id, start, page_size)
            raw_rows = payload.get("rows") or []
            if not raw_rows:
                break
            rows = self._rows_from_entry_payload(raw_rows, columns)
            for row in rows:
                supplier = str(_cell_value(row.get("FSupplierId.FName")) or "")
                if keywords and not any(k in supplier for k in keywords):
                    continue
                bill = str(_cell_value(row.get("FBillNo")) or "").strip()
                mat = str(_cell_value(row.get("FMaterialId.FNumber")) or "").strip()
                if not bill or not mat:
                    continue
                fdate = str(_cell_value(row.get("FDate")) or "")[:10].replace("/", "-")
                if cutoff and fdate and fdate < cutoff:
                    continue
                qty = _parse_number(row.get("FQty"))
                tax_price = _parse_number(row.get("FTaxPrice"))
                tax_amount = _parse_number(row.get("FAllAmount"))
                if tax_amount <= 0 and tax_price > 0 and qty > 0:
                    tax_amount = tax_price * qty
                close_mrp = str(_cell_value(row.get("FMRPCloseStatus")) or "").strip()
                close_bill = str(_cell_value(row.get("FCloseStatus")) or "").strip()
                closed = close_mrp in ("Y", "关闭", "B") or close_bill in ("Y", "关闭", "B")
                receive_qty = qty if closed else 0.0
                remain = 0.0 if closed else qty
                row["FTaxPrice"] = tax_price
                row["FAllAmount"] = tax_amount
                row["FReceiveQty"] = receive_qty
                row["FRemainReceiveQty"] = remain
                row["_pur_closed"] = closed
                out.append(row)
            if len(raw_rows) < page_size:
                break

        logger.info(
            "永联 PUR 鼎雄采购行 %s 条（keywords=%s, max_scan=%s）",
            len(out),
            keywords,
            max_scan,
        )
        return out

    async def fetch_supplier_price_map(
        self,
        *,
        supplier_keywords: Tuple[str, ...] = YONGLIAN_SUPPLIER_KEYWORDS,
        needed_keys: Optional[set] = None,
        max_scan: int = 80000,
        page_size: int = 1000,
        date_from: Optional[str] = None,
        lines: Optional[List[dict]] = None,
    ) -> Dict[Tuple[str, str], dict]:
        """从 PUR 鼎雄行构建 {(单据号, 物料编码): {tax_price, tax_amount, qty}}。"""
        if lines is None:
            lines = await self.fetch_supplier_purchase_lines(
                supplier_keywords=supplier_keywords,
                max_scan=max_scan,
                page_size=page_size,
                date_from=date_from,
            )
        price_map: Dict[Tuple[str, str], dict] = {}
        pending = set(needed_keys) if needed_keys else None
        for row in lines:
            bill = str(_cell_value(row.get("FBillNo")) or "").strip()
            mat = str(_cell_value(row.get("FMaterialId.FNumber")) or "").strip()
            tax_price = _parse_number(row.get("FTaxPrice"))
            tax_amount = _parse_number(row.get("FAllAmount"))
            qty = _parse_number(row.get("FQty"))
            if tax_price <= 0 and tax_amount <= 0:
                continue
            key = (bill, mat)
            price_map[key] = {
                "tax_price": tax_price,
                "tax_amount": tax_amount,
                "qty": qty,
            }
            if pending is not None:
                pending.discard(key)
        logger.info(
            "永联 PUR 单价映射 %s 条（pending=%s）",
            len(price_map),
            len(pending) if pending is not None else "n/a",
        )
        return price_map

    @staticmethod
    def merge_price_map_into_rows(rows: List[dict], price_map: Dict[Tuple[str, str], dict]) -> int:
        """把 PUR 单价合并进 SCP 行；返回成功合并行数。"""
        if not rows or not price_map:
            return 0
        n = 0
        for row in rows:
            bill = str(_cell_value(row.get("FBillNo")) or "").strip()
            mat = str(_cell_value(row.get("FMaterialId.FNumber")) or "").strip()
            info = price_map.get((bill, mat))
            if not info:
                continue
            tax_price = float(info.get("tax_price") or 0)
            tax_amount = float(info.get("tax_amount") or 0)
            if tax_price > 0:
                row["FTaxPrice"] = tax_price
            if tax_amount > 0:
                row["FAllAmount"] = tax_amount
            n += 1
        return n

    @staticmethod
    def _normalize_list_rows(data: Any) -> List[dict]:
        if isinstance(data, list):
            if data and all(isinstance(x, list) for x in data):
                return KingdeeScpClient._rows_to_dicts_from_matrix(data)
            dict_rows = [x for x in data if isinstance(x, dict)]
            if dict_rows:
                return dict_rows
        if isinstance(data, dict):
            for key in ("Rows", "rows", "Data", "data", "result", "Result"):
                val = data.get(key)
                if isinstance(val, list):
                    return KingdeeScpClient._normalize_list_rows(val)
        return []

    @staticmethod
    def _rows_to_dicts_from_matrix(rows: List[list]) -> List[dict]:
        if not rows:
            return []
        if all(isinstance(x, dict) for x in rows):
            return rows  # type: ignore[return-value]
        keys = [
            "FBillNo",
            "FDate",
            "FMaterialId.FNumber",
            "FMaterialId.FName",
            "FMaterialId.FSpecification",
            "FQty",
            "FDeliveryDate",
            "FTaxPrice",
            "FAllAmount",
            "FDocumentStatus",
            "FReceiveQty",
            "FRemainReceiveQty",
        ]
        items = []
        for row in rows:
            if not isinstance(row, list):
                continue
            items.append({keys[i]: row[i] if i < len(row) else None for i in range(len(keys))})
        return items

    async def fetch_all_order_lines(self, date_from: Optional[str] = None) -> Tuple[List[dict], int]:
        await self.login()
        rows = await self.fetch_purchase_orders(date_from=date_from)
        live_rows = []
        for row in rows:
            close_status = str(row.get("FMRPCloseStatus") or "").strip()
            remain = float(row.get("FRemainReceiveQty") or 0)
            qty = float(row.get("FQty") or 0)
            if close_status in ("关闭", "B") and remain <= 0 and qty > 0:
                continue
            if close_status in ("关闭", "B") and remain <= 0:
                continue
            live_rows.append(row)
        results = [{"head": {}, "line": row, "closed": False} for row in live_rows]
        return results, len(live_rows)
