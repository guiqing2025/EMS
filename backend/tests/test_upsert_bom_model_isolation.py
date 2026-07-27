"""同采购单多机型 BOM 导入不得互相覆盖。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bom_excel import ParsedBom, ParsedBomLine, upsert_bom_model
from database import Base
from models import BomLine, BomModel, SrmOrder


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[SrmOrder.__table__, BomModel.__table__, BomLine.__table__])
    return sessionmaker(bind=engine)()


def _parsed(model_code: str, material_code: str) -> ParsedBom:
    return ParsedBom(
        model_code=model_code,
        model_name=None,
        model_spec=None,
        lines=[
            ParsedBomLine(
                seq="1",
                material_code=material_code,
                material_name="R",
                spec=None,
                unit="PCS",
                qty_per=1.0,
                position=None,
                process=None,
                remark=None,
                sort_order=1,
            )
        ],
        folder_name=model_code,
        source_file=f"{model_code}.xlsx",
        source_mtime=1.0,
    )


def test_same_po_two_models_keep_separate_boms():
    db = _session()
    pn = "3502-260714005"
    cid = "enjiu"
    db.add(
        SrmOrder(
            line_key="a",
            purchase_no=pn,
            product_goods_no="03029690",
            customer_id=cid,
            is_completed=False,
        )
    )
    db.add(
        SrmOrder(
            line_key="b",
            purchase_no=pn,
            product_goods_no="03029692",
            customer_id=cid,
            is_completed=False,
        )
    )
    db.commit()

    row1, created1, _ = upsert_bom_model(
        db, "A116", cid, "恩玖", _parsed("03029690", "MAT-690"), purchase_no=pn
    )
    db.commit()
    assert created1 == 1
    id1 = row1.id
    lines1 = [x.material_code for x in db.query(BomLine).filter(BomLine.bom_model_id == id1).all()]
    assert lines1 == ["MAT-690"]

    row2, created2, _ = upsert_bom_model(
        db, "A116", cid, "恩玖", _parsed("03029692", "MAT-692"), purchase_no=pn
    )
    db.commit()
    assert created2 == 1
    assert row2.id != id1

    # 第一份 BOM 明细不得被第二份覆盖
    still = [x.material_code for x in db.query(BomLine).filter(BomLine.bom_model_id == id1).all()]
    assert still == ["MAT-690"]
    lines2 = [x.material_code for x in db.query(BomLine).filter(BomLine.bom_model_id == row2.id).all()]
    assert lines2 == ["MAT-692"]

    o690 = db.query(SrmOrder).filter(SrmOrder.product_goods_no == "03029690").one()
    o692 = db.query(SrmOrder).filter(SrmOrder.product_goods_no == "03029692").one()
    assert o690.bom_model_id == id1
    assert o692.bom_model_id == row2.id


def test_same_model_reimport_updates_inplace():
    db = _session()
    pn = "3502-TEST-REIMPORT"
    cid = "enjiu"
    db.add(
        SrmOrder(
            line_key="r1",
            purchase_no=pn,
            product_goods_no="03029690",
            customer_id=cid,
            is_completed=False,
        )
    )
    db.commit()

    row1, c1, _ = upsert_bom_model(
        db, "A116", cid, "恩玖", _parsed("03029690", "MAT-OLD"), purchase_no=pn
    )
    db.commit()
    row2, c2, u2 = upsert_bom_model(
        db, "A116", cid, "恩玖", _parsed("03029690", "MAT-NEW"), purchase_no=pn
    )
    db.commit()
    assert c1 == 1
    assert c2 == 0
    assert u2 == 1
    assert row2.id == row1.id
    lines = [x.material_code for x in db.query(BomLine).filter(BomLine.bom_model_id == row1.id).all()]
    assert lines == ["MAT-NEW"]
