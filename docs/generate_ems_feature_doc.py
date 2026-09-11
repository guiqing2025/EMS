#!/usr/bin/env python3
"""生成 EMS 系统功能介绍 Word 文档"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

OUTPUT = Path(__file__).resolve().parent / "EMS系统功能介绍.docx"


def set_cell_shading(cell, color: str = "D9E2F3") -> None:
    from docx.oxml import OxmlElement

    tc_pr = cell._element.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), color)
    shd.set(qn("w:val"), "clear")
    tc_pr.append(shd)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], header_fill: str = "2F5496") -> None:
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    hdr = table.rows[0].cells
    for i, text in enumerate(headers):
        hdr[i].text = text
        for p in hdr[i].paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)
                run.font.size = Pt(10)
        set_cell_shading(hdr[i], header_fill)
    for r_idx, row in enumerate(rows):
        cells = table.rows[r_idx + 1].cells
        for c_idx, text in enumerate(row):
            cells[c_idx].text = text
            for p in cells[c_idx].paragraphs:
                for run in p.runs:
                    run.font.size = Pt(10)
    doc.add_paragraph()


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.name = "微软雅黑"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def add_para(doc: Document, text: str, bold: bool = False) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "微软雅黑"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    run.font.size = Pt(11)
    run.bold = bold


def build() -> Path:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("深圳市景立科技有限公司\nEMS 生产管理系统\n功能介绍")
    tr.bold = True
    tr.font.size = Pt(22)
    tr.font.name = "微软雅黑"
    tr._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    tr.font.color.rgb = RGBColor(47, 84, 150)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run("文档版本：V1.0  |  适用系统：EMS 订单中心")
    sr.font.size = Pt(10)
    sr.font.color.rgb = RGBColor(100, 100, 100)

    doc.add_paragraph()

    add_heading(doc, "一、系统总览", 1)
    add_table(
        doc,
        ["项目", "说明"],
        [
            ["系统名称", "EMS 生产管理系统（订单中心）"],
            ["适用客户", "按本机工程客户配置"],
            ["数据来源", "客户 SRM 自动同步 + 共享盘 Excel + 手工导入"],
            ["数据库", "本地 SQLite（ems.db），建议单机部署"],
            ["访问方式", "浏览器打开 http://服务器IP:8000，内网多人共用"],
            ["账号角色", "管理员 / 计划员 / 仓库 / SMT 部门 / DIP 部门"],
        ],
    )

    add_heading(doc, "二、功能模块一览", 1)
    add_table(
        doc,
        ["模块", "主要用户", "核心能力"],
        [
            ["订单列表", "全员", "SRM 订单同步、查询、导出、手动录单"],
            ["仓库管理", "仓库管理员", "库存、来料、发料、退料、流水、共享盘同步"],
            ["工程", "计划员", "BOM、贴装判定、齐套试算、客户资料、替代料、工装"],
            ["计划排产", "计划员", "SMT/DIP 排程、备料/工装状态"],
            ["部门领料", "SMT / DIP", "领料确认、退料申请（手机友好）"],
            ["包装发货", "包装人员", "扫码装箱、发货出单、打印出货单"],
            ["数据看板", "管理层", "订单统计、月度费用（可选密码）"],
        ],
    )

    add_heading(doc, "三、订单列表", 1)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["SRM 自动同步", "定时/手动从已配置 SRM 拉取在制订单"],
            ["订单查询", "按客户、订单号、料号、品名、日期、SRM 状态、收货状态筛选"],
            ["订单导出", "导出 XLSX 表格"],
            ["手动录单", "无 SRM 的小客户可手工录入，支持后续扫码发货"],
            ["客户齐套", "已配置客户展示 SRM 齐套信息；结合 EMS BOM 计算备料齐套"],
            ["结案归档", "已完成订单在本系统保留，不导入客户历史已结案单"],
            ["绑定 BOM", "订单与工程 BOM 机型自动/手工关联"],
            ["包装扫码", "按订单扫 PCBA 条码，累计待发货数量"],
            ["发货确认", "生成出货单号，打印出货单，更新已发货数量"],
            ["同步通知", "新订单、齐套变化提醒"],
        ],
    )

    add_heading(doc, "四、仓库管理", 1)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["库存明细", "按客户 + 料号管理库存，显示可用量、合并替代料库存"],
            ["来料入账", "手工登记来料，写入流水"],
            ["发料出库", "向 SMT / DIP 部门发料，锁定库存"],
            ["退料审核", "部门退料申请，仓库确认入库"],
            ["流水账", "来料、发料、退料等全链路记录"],
            ["共享盘导入", "从进销存 Excel「库存表」同步库存"],
            ["导出库存", "导出当前库存表"],
            ["替代料合并", "客户料号（如 00A）与我司料号（如 00）库存合并显示"],
            ["导入模板", "下载标准物料主数据模板"],
        ],
    )
    add_para(doc, "库存口径：客户 + 物料编码唯一；可用库存 = 库存数量 − 发料锁定数量。")

    add_heading(doc, "五、工程模块", 1)

    add_heading(doc, "5.1 BOM 机型", 2)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["BOM 导入", "从 Excel 导入机型 BOM（共享盘或手工上传）"],
            ["BOM 明细", "查看序号、料号、品名、规格、用量、位号、工艺"],
            ["贴装自动判定", "根据坐标 + 规则自动识别 SMT/DIP、TOP/BOT"],
            ["贴装画像", "自动识别纯贴片 / 纯插件 / 混贴，可手工覆盖"],
            ["备料齐套试算", "按试算数量对比仓库库存，显示齐 / 部分 / 欠料"],
            ["替代料展示", "齐套试算中显示可替代料及各自库存"],
            ["导出 BOM", "含贴装、面别信息的 BOM 导出"],
            ["订单绑定", "将 SRM 订单与 BOM 机型关联"],
        ],
    )

    add_heading(doc, "5.2 客户资料", 2)
    add_table(
        doc,
        ["资料类型", "用途", "支持格式"],
        [
            ["贴片坐标", "判定 SMT/DIP、面别 TOP/BOT", "Altium CSV/TXT、AIS 坐标、ASC xlsx、ZIP"],
            ["Gerber 制板", "制板资料归档与合规审核", "ZIP（.gdo/.gbr 等制板层）"],
            ["位号图", "装配核对、PDF 预览翻页", "PDF、ZIP"],
        ],
    )
    add_para(doc, "导入后自动审核；坐标/Gerber/位号图可收起展开、整包清除。")

    add_heading(doc, "5.3 替代料", 2)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["替代表同步", "从「替代料06-03.xls」同步规则"],
            ["替代关系查询", "主件 ↔ 替代料、机型、生效日期等"],
            ["齐套/库存联动", "BOM 用料号可匹配关联替代料库存"],
        ],
    )

    add_heading(doc, "5.4 工序对照", 2)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["工艺明细同步", "从共享盘工艺明细导入"],
            ["工序勾选", "按机型配置 SMT、DIP、测试等工序路线"],
            ["排产引用", "计划排产时显示工艺路线"],
        ],
    )

    add_heading(doc, "5.5 工装登记", 2)
    add_table(
        doc,
        ["工装类型", "登记内容"],
        [
            ["钢网", "编码、版本、数量、入库时间"],
            ["波峰治具", "编码、版本、数量、入库时间"],
            ["ICT/FCT 测试工装", "编码、版本、数量、入库时间"],
        ],
    )

    add_heading(doc, "六、计划排产", 1)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["SMT / DIP 分线", "两条排产表独立管理"],
            ["从订单导入", "将订单行导入排产"],
            ["排产编辑", "线别、订单、型号、工艺、订单量、交期、日计划、状态、备注"],
            ["备料状态", "关联 BOM 齐套结果，可刷新"],
            ["工装状态", "关联工程工装登记"],
            ["拖拽排序", "调整排产优先级"],
        ],
    )

    add_heading(doc, "七、部门领料（SMT / DIP）", 1)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["待确认领料", "仓库发料后，部门手机/电脑确认收货"],
            ["申请退料", "填写数量提交退料申请"],
            ["我的退料", "查看退料单状态"],
            ["界面适配", "手机端优先布局"],
        ],
    )

    add_heading(doc, "八、包装发货", 1)
    add_table(
        doc,
        ["功能", "说明"],
        [
            ["扫码入库", "扫码枪扫 PCBA 条码，累计待发货"],
            ["防重复", "同一条码不可重复扫描"],
            ["发货确认", "填写发货日期、物流等，生成出货单"],
            ["打印出货单", "浏览器打印出货单"],
            ["数量跟踪", "订单列表显示待发货 / 已发货"],
        ],
    )

    add_heading(doc, "九、数据同步与集成", 1)
    add_table(
        doc,
        ["集成对象", "同步内容", "方式"],
        [
            ["客户A SRM", "采购订单、交货/收货数量", "API 定时同步"],
            ["客户B SRM", "订单数据", "API 定时同步"],
            ["客户C 金蝶 SCP", "订单数据", "API 定时同步"],
            ["共享盘进销表", "仓库库存", "Excel「库存表」导入"],
            ["工程资料", "BOM、坐标、Gerber / 位号图", "人工导入（不从本地共享盘同步）"],
            ["替代料表", "替代规则", "Excel 同步"],
            ["工艺明细", "工序路线", "Excel 同步"],
        ],
    )

    add_heading(doc, "十、权限说明", 1)
    add_table(
        doc,
        ["角色", "可见模块"],
        [
            ["管理员", "全部模块"],
            ["计划员（planner）", "订单、工程、计划排产"],
            ["仓库（warehouse）", "订单、仓库管理"],
            ["SMT / DIP 部门", "订单（只读）、部门领料"],
        ],
    )

    add_heading(doc, "十一、部署与运行条件", 1)
    add_table(
        doc,
        ["项目", "要求"],
        [
            ["操作系统", "Windows 10/11 或 macOS"],
            ["运行环境", "Python 3.9+，单机常驻运行服务"],
            ["内存", "建议 8GB 及以上"],
            ["网络", "内网互通；能访问 SRM 与共享盘（如 192.168.2.11）"],
            ["防火墙", "放行 8000 端口供同事浏览器访问"],
            ["数据库", "ems.db 放在本机，勿放网络共享盘"],
        ],
    )

    add_heading(doc, "十二、当前限制与说明", 1)
    add_table(
        doc,
        ["项目", "说明"],
        [
            ["面别判定", "仅来自贴片坐标；Gerber、位号图不定面别"],
            ["齐套规则", "部分客户不展示 SRM 客户齐套字段"],
            ["单机部署", "建议一台电脑常驻运行，其他人浏览器访问"],
            ["共享盘路径", "需在 srm_config.json 配置为本机可访问路径"],
            ["历史订单", "不同步客户系统已结案的历史单"],
        ],
    )

    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run("深圳市景立科技有限公司 · EMS 生产管理系统")
    fr.font.size = Pt(9)
    fr.font.color.rgb = RGBColor(128, 128, 128)

    doc.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    path = build()
    print(path)
