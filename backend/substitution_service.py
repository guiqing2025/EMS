"""客户替代料规则（按 customer_id 隔离）"""
from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_code(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().upper().replace(" ", "")


# customer_id -> {mtime, groups, meta, primary_of, checked_at}
_CACHE_BY_CUSTOMER: dict[str, dict] = {}
_CACHE_TTL_SEC = 60.0


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, node: str) -> str:
        if node not in self.parent:
            self.parent[node] = node
        if self.parent[node] != node:
            self.parent[node] = self.find(self.parent[node])
        return self.parent[node]

    def union(self, a: str, b: str) -> None:
        if not a or not b or a == b:
            return
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _load_rules_from_rows(rows: list[dict]) -> tuple[dict[str, set[str]], dict[str, dict]]:
    uf = _UnionFind()
    meta: dict[str, dict] = {}
    for item in rows:
        comp_code = item["comp_code"]
        sub_code = item["sub_code"]
        uf.union(comp_code, sub_code)
        meta[comp_code] = {
            "material_code": comp_code,
            "material_name": item.get("comp_name") or "",
            "spec": item.get("comp_spec") or "",
        }
        meta[sub_code] = {
            "material_code": sub_code,
            "material_name": item.get("sub_name") or "",
            "spec": item.get("sub_spec") or "",
        }
    groups: dict[str, set[str]] = {}
    for code in meta:
        root = uf.find(code)
        groups.setdefault(root, set()).add(code)
    code_groups: dict[str, set[str]] = {}
    for members in groups.values():
        for code in members:
            code_groups[code] = members
    return code_groups, meta


def _build_primary_of(rows: list[dict]) -> dict[str, str]:
    """sub_code → 首个 comp_code（客户替代料映射到我司主料号）。"""
    primary_of: dict[str, str] = {}
    for item in rows:
        sub = normalize_code(item.get("sub_code"))
        comp = normalize_code(item.get("comp_code"))
        if sub and comp and sub not in primary_of:
            primary_of[sub] = comp
    return primary_of


def _empty_bucket() -> dict:
    return {
        "mtime": None,
        "groups": {},
        "meta": {},
        "primary_of": {},
        "edges": [],
        "checked_at": 0.0,
    }


def _bucket(customer_id: str) -> dict:
    cid = (customer_id or "").strip()
    if not cid:
        return _empty_bucket()
    if cid not in _CACHE_BY_CUSTOMER:
        _CACHE_BY_CUSTOMER[cid] = _empty_bucket()
    return _CACHE_BY_CUSTOMER[cid]


def reload_substitution_cache_from_db(db, customer_id: Optional[str] = None) -> int:
    """重载缓存。customer_id 为空时重载全部客户。"""
    from models import SubstitutionRule

    if customer_id:
        customers = [(customer_id or "").strip()]
    else:
        customers = [
            r[0]
            for r in db.query(SubstitutionRule.customer_id).distinct().all()
            if (r[0] or "").strip()
        ]
        # 清空未出现在库中的缓存桶
        for stale in list(_CACHE_BY_CUSTOMER.keys()):
            if stale not in customers:
                _CACHE_BY_CUSTOMER.pop(stale, None)

    total = 0
    for cid in customers:
        if not cid:
            continue
        rows = db.query(SubstitutionRule).filter(SubstitutionRule.customer_id == cid).all()
        bucket = _bucket(cid)
        if not rows:
            bucket.update(_empty_bucket())
            continue
        payload = [
            {
                "comp_code": r.comp_code,
                "comp_name": r.comp_name,
                "comp_spec": r.comp_spec,
                "sub_code": r.sub_code,
                "sub_name": r.sub_name,
                "sub_spec": r.sub_spec,
                "parent_code": r.parent_code or "",
                "qty": r.qty,
            }
            for r in rows
        ]
        groups, meta = _load_rules_from_rows(payload)
        edges = [
            {
                "comp_code": normalize_code(p["comp_code"]),
                "sub_code": normalize_code(p["sub_code"]),
                "parent_code": normalize_code(p.get("parent_code")),
                "qty": p.get("qty"),
            }
            for p in payload
            if normalize_code(p.get("comp_code")) and normalize_code(p.get("sub_code"))
        ]
        latest_ts = None
        for r in rows:
            if r.synced_at:
                ts = r.synced_at.timestamp()
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts
        bucket["mtime"] = latest_ts
        bucket["groups"] = groups
        bucket["meta"] = meta
        bucket["primary_of"] = _build_primary_of(payload)
        bucket["edges"] = edges
        bucket["checked_at"] = time.time()
        total += len(rows)
    return total


def _edge_applies(edge: dict, parent_code: str = "", *, customer_id: str = "") -> bool:
    """
    永联：parent 非空时仅匹配当前机型；parent 空则全局。
    其它客户（如菲利斯）：历史数据大量带 parent 但不参与过滤，保持全局并查。
    """
    cid = (customer_id or "").strip().lower()
    if cid not in ("yonglian", "a067"):
        return True
    ep = normalize_code(edge.get("parent_code"))
    if not ep:
        return True
    pc = normalize_code(parent_code)
    if not pc:
        return True  # 未指定机型时（仓库总览）仍可见
    return ep == pc


def iter_applicable_edges(customer_id: str, material_code: str, parent_code: str = "") -> list[dict]:
    bucket = _ensure_loaded(customer_id)
    code = normalize_code(material_code)
    if not code:
        return []
    out = []
    for edge in bucket.get("edges") or []:
        if edge["comp_code"] != code and edge["sub_code"] != code:
            continue
        if not _edge_applies(edge, parent_code, customer_id=customer_id):
            continue
        out.append(edge)
    return out


def get_rule_qty_per(material_code: str, customer_id: str = "", parent_code: str = "") -> Optional[float]:
    """命中「元件=料号」且带 qty 的规则时返回每套用量；优先精确 parent 匹配。"""
    # 仅永联用规则 qty 覆盖 BOM 用量；其它客户仍用 BOM qty_per
    if (customer_id or "").strip().lower() not in ("yonglian", "a067"):
        return None
    code = normalize_code(material_code)
    pc = normalize_code(parent_code)
    exact: Optional[float] = None
    global_qty: Optional[float] = None
    for edge in iter_applicable_edges(customer_id, code, parent_code):
        if edge["comp_code"] != code:
            continue
        q = edge.get("qty")
        if q is None:
            continue
        ep = normalize_code(edge.get("parent_code"))
        if pc and ep == pc:
            exact = float(q)
        elif not ep:
            global_qty = float(q)
    if exact is not None:
        return exact
    return global_qty


def count_rules_by_parent(db, customer_id: str, parent_codes: list[str]) -> dict[str, int]:
    """parent_code → 规则条数（用于订单机型列表打标）。"""
    from models import SubstitutionRule
    from sqlalchemy import func

    cid = (customer_id or "").strip()
    codes = [normalize_code(c) for c in parent_codes if normalize_code(c)]
    if not cid or not codes:
        return {}
    # DB 中 parent 可能大小写不一，用 upper 比较困难；先按原码查再兜底
    rows = (
        db.query(SubstitutionRule.parent_code, func.count(SubstitutionRule.id))
        .filter(
            SubstitutionRule.customer_id == cid,
            SubstitutionRule.parent_code.in_(list({c for c in parent_codes if c})),
        )
        .group_by(SubstitutionRule.parent_code)
        .all()
    )
    out = {normalize_code(p): int(n) for p, n in rows if p}
    # 若库内大小写与 model_code 不一致，再扫一遍
    if len(out) < len(set(normalize_code(c) for c in parent_codes if c)):
        all_rows = (
            db.query(SubstitutionRule.parent_code)
            .filter(SubstitutionRule.customer_id == cid, SubstitutionRule.parent_code != "")
            .all()
        )
        from collections import Counter

        ctr = Counter(normalize_code(r[0]) for r in all_rows if r[0])
        want = {normalize_code(c) for c in parent_codes if c}
        for k, n in ctr.items():
            if k in want:
                out[k] = n
    return out


def _ensure_loaded(customer_id: str) -> dict:
    cid = (customer_id or "").strip()
    if not cid:
        return _empty_bucket()

    bucket = _bucket(cid)
    now = time.time()
    if bucket["groups"] and (now - float(bucket.get("checked_at") or 0)) < _CACHE_TTL_SEC:
        return bucket

    from database import SessionLocal
    from models import SubstitutionRule

    db = SessionLocal()
    try:
        latest = (
            db.query(SubstitutionRule.synced_at)
            .filter(SubstitutionRule.customer_id == cid)
            .order_by(SubstitutionRule.id.desc())
            .first()
        )
        ts = latest[0].timestamp() if latest and latest[0] else None
        if bucket["groups"] and bucket["mtime"] == ts and bucket.get("primary_of") is not None:
            bucket["checked_at"] = now
            return bucket
        reload_substitution_cache_from_db(db, cid)
        return _bucket(cid)
    finally:
        db.close()


def get_substitute_codes(material_code: str, customer_id: str = "") -> list[str]:
    bucket = _ensure_loaded(customer_id)
    code = normalize_code(material_code)
    if not code:
        return []
    members = bucket["groups"].get(code, set())
    return sorted(m for m in members if m != code)


def get_substitute_group(material_code: str, customer_id: str = "") -> set[str]:
    bucket = _ensure_loaded(customer_id)
    code = normalize_code(material_code)
    if not code:
        return set()
    return set(bucket["groups"].get(code, {code}))


def get_stock_primary_code(material_code: str, customer_id: str = "") -> str:
    """客户替代料号映射为我司仓库存储主料号（替代表 comp_code）。"""
    bucket = _ensure_loaded(customer_id)
    code = normalize_code(material_code)
    if not code:
        return ""
    return bucket.get("primary_of", {}).get(code) or code


def is_substitute_alias_code(material_code: str, customer_id: str = "") -> bool:
    code = normalize_code(material_code)
    primary = get_stock_primary_code(code, customer_id)
    return bool(code and primary and primary != code)


def _raw_stock_from_stock_map(stock_map: dict, code: str) -> float:
    mat = stock_map.get(normalize_code(code))
    if not mat:
        return 0.0
    return float(mat.qty) - float(mat.locked_qty)


def _available_from_stock_map(stock_map: dict, code: str) -> float:
    return max(_raw_stock_from_stock_map(stock_map, code), 0.0)


def _kitting_supply_qty(own_stock: float, substitute_stocks: list[float]) -> float:
    return max(own_stock, 0.0)


def evaluate_kitting_line(
    required: float,
    own_stock: float,
    substitutes: list[dict],
    *,
    excel_in_qty: Optional[float] = None,
    excel_demand_qty: Optional[float] = None,
) -> dict[str, object]:
    required = float(required or 0)
    own_stock = float(own_stock or 0)
    sub_stocks = [
        float(s.get("stock_qty", s.get("available_qty")) or 0)
        for s in (substitutes or [])
    ]
    best_sub = max(sub_stocks) if sub_stocks else 0.0

    owe = max(-own_stock, 0.0)
    if excel_in_qty is not None and excel_demand_qty is not None:
        owe = max(float(excel_demand_qty) - float(excel_in_qty), 0.0)

    main_gap = max(required - own_stock, 0.0)

    substitute_covered = False
    supply = max(own_stock, 0.0) + sum(max(float(s), 0.0) for s in sub_stocks)

    if main_gap > 0:
        if best_sub >= main_gap:
            substitute_covered = True
            shortage = 0.0
            status = "ready"
            supply = max(supply, best_sub)
        else:
            shortage = main_gap - best_sub
            status = "partial" if best_sub > 0 else "shortage"
    else:
        if own_stock < 0 and owe > 0 and substitutes and best_sub >= owe:
            substitute_covered = True
        shortage = 0.0
        status = "ready"

    return {
        "shortage_qty": shortage,
        "status": status,
        "substitute_covered": substitute_covered,
        "kitting_supply_qty": supply,
        "ledger_owe_qty": owe,
        "main_gap_qty": main_gap,
    }


def resolve_group_stock(
    material_code: str,
    stock_map: dict,
    customer_id: str = "",
    *,
    parent_code: str = "",
) -> dict[str, object]:
    """按料号独立展示库存；齐套时替代料库存可计入供给量，但不合并显示。"""
    bucket = _ensure_loaded(customer_id)
    code = normalize_code(material_code)
    primary = get_stock_primary_code(code, customer_id)
    edges = iter_applicable_edges(customer_id, code, parent_code)
    if edges:
        group = {code}
        for e in edges:
            group.add(e["comp_code"])
            group.add(e["sub_code"])
    else:
        # 无适用边：永联在指定机型下表示本行无替代；其它客户回退全局组
        cid = (customer_id or "").strip().lower()
        if cid in ("yonglian", "a067") and parent_code and (bucket.get("edges") or []):
            group = {code}
        else:
            group = get_substitute_group(code, customer_id) or {code}
    own_stock_qty = _raw_stock_from_stock_map(stock_map, code)
    own_available = _available_from_stock_map(stock_map, code)
    substitutes = []
    substitute_stocks: list[float] = []
    for alt in sorted(group):
        if alt == code:
            continue
        meta = bucket.get("meta", {}).get(alt, {})
        mat = stock_map.get(alt)
        alt_stock = _raw_stock_from_stock_map(stock_map, alt)
        alt_avail = _available_from_stock_map(stock_map, alt)
        substitute_stocks.append(alt_stock)
        substitutes.append(
            {
                "material_code": alt,
                "material_name": meta.get("material_name") or (mat.material_name if mat else ""),
                "spec": meta.get("spec") or (mat.spec if mat else ""),
                "stock_qty": alt_stock,
                "available_qty": alt_avail,
                "is_primary": alt == primary,
            }
        )
    kitting_supply_qty = _kitting_supply_qty(own_stock_qty, substitute_stocks)
    return {
        "material_code": code,
        "stock_primary_code": primary,
        "is_substitute_alias": primary != code,
        "own_stock_qty": own_stock_qty,
        "own_available_qty": own_available,
        "kitting_supply_qty": kitting_supply_qty,
        "group_available_qty": own_available,
        "substitute_codes": [s["material_code"] for s in substitutes],
        "substitutes": substitutes,
    }


def get_substitute_meta(material_code: str, customer_id: str = "") -> Optional[dict]:
    bucket = _ensure_loaded(customer_id)
    return bucket["meta"].get(normalize_code(material_code))


def build_substitute_details(
    material_code: str,
    stock_map: dict,
    *,
    customer_id: str = "",
    parent_code: str = "",
    only_with_stock: bool = False,
) -> list[dict]:
    """返回可替代料号及库存；默认列出规则内全部替代料。"""
    info = resolve_group_stock(material_code, stock_map, customer_id, parent_code=parent_code)
    details: list[dict] = []
    for alt in info.get("substitutes") or []:
        if only_with_stock and float(alt.get("stock_qty", alt.get("available_qty")) or 0) <= 0:
            continue
        details.append(alt)
    return details
