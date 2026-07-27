"""物料管制单文本解析回归（不依赖 OCR）。"""
from material_control_parse import parse_control_text
from material_control_service import _is_partial_batch_control


# 模拟 GZ2026070806：工单总量 10000，三批各 500 分别换不同位号
_GZ2026070806_OCR = """
广州菲利斯太阳能科技有限公司
物料管制单
管制单号
GZ2026070806
管制机型：IVEM12048-II
管制原因/主旨说明：替代料管制验证
管制处理方式：
1、管制120-300056-0
(PCBA,IVBM12048-II)，如下：
成品料号信息
管制类型
管制料号
工单号*数量
管制数量
删除物料*用量
位号
增加物料*用量
位号
PCBA管制
500
110-200047-00*2PCS
U7，U31
110-200094-00*2PCS
U7, U31
PCBA管制
500
110-200089-00*2PCS
U28,U29
110-200236-00A*2PCS
U28,U29
PCBA管制
500
110-100073-00*1PCS
U33
110-200151-00A*1PCS
U33
管制结果
整机工单号*数量：
S103-20260626091 x 10000
"""


def test_gz2026070806_batch_lots():
    r = parse_control_text(_GZ2026070806_OCR)
    f = r["fields"]
    assert f["control_no"] == "GZ2026070806"
    assert f["model_code"] == "120-300056-00"
    assert len(f["groups"]) == 1
    g = f["groups"][0]
    assert g["model_code"] == "120-300056-00"
    assert len(g["orders"]) == 1
    o = g["orders"][0]
    assert o["purchase_no"] == "5103-20260626091"
    assert o["order_qty"] == 10000.0
    assert o["control_qty"] == 1500.0  # 三批合计
    assert len(g["changes"]) == 3
    assert g["changes"][0]["control_qty"] == 500.0
    assert g["changes"][0]["remove_code"] == "110-200047-00"
    assert g["changes"][0]["add_code"] == "110-200094-00"
    assert "U7" in (g["changes"][0].get("remove_refdes") or "")
    assert g["changes"][1]["control_qty"] == 500.0
    assert g["changes"][1]["remove_code"] == "110-200089-00"
    assert g["changes"][2]["control_qty"] == 500.0
    assert g["changes"][2]["remove_code"] == "110-100073-00"
    # 确认逻辑应识别为分批
    assert _is_partial_batch_control(
        [type("O", (), o)()],
        [type("C", (), c)() for c in g["changes"]],
    )


def test_classic_full_order_control():
    text = """
    管制单号 GZ2026033001
    管制料号 120-200235-09
    管制原因/主旨说明：停产物料在途工单管制
    5105-20260224003*10000
    110-100050-00*2
    U2,U3
    110-100138-00*2
    """
    r = parse_control_text(text)
    f = r["fields"]
    assert f["control_no"] == "GZ2026033001"
    assert "120-200235-09" in f["model_code"]
    assert any(o["purchase_no"] == "5105-20260224003" for o in f["orders"])
    o = next(x for x in f["orders"] if x["purchase_no"] == "5105-20260224003")
    assert o["order_qty"] == 10000.0
