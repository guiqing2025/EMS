"""恩玖订单隔离：同料号不同采购单不共用坐标/Gerber。"""
from types import SimpleNamespace

from eng_asset_scope import _pick_asset, assets_scope_for
from eng_customer_rules import get_customer_rules


def test_a116_assets_scope_is_order():
    assert assets_scope_for("A116") == "order"
    assert (get_customer_rules("A116").get("assets_scope") or "").lower() == "order"


def test_pick_asset_order_scope_ignores_other_po():
    bom = SimpleNamespace(id=30, purchase_no="3502-260724002", model_code="03029467")
    other = SimpleNamespace(id=1, bom_model_id=10, purchase_no="3502-260713007")
    same_po = SimpleNamespace(id=2, bom_model_id=30, purchase_no="3502-260724002")
    # 其它订单资料不得挂上
    assert _pick_asset([other], bom, order_scope=True) is None
    # 本订单资料可用
    assert _pick_asset([other, same_po], bom, order_scope=True) is same_po
    # 误把其它 PO 的行绑到本 bom_model_id，仍拒绝（purchase_no 不一致）
    hijacked = SimpleNamespace(id=3, bom_model_id=30, purchase_no="3502-260713007")
    assert _pick_asset([hijacked], bom, order_scope=True) is None


if __name__ == "__main__":
    test_a116_assets_scope_is_order()
    test_pick_asset_order_scope_ignores_other_po()
    print("OK")
