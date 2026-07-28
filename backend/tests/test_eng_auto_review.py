"""工程资料自动审核：齐套通过则 auto approve，缺项则跳过。"""
from __future__ import annotations

from eng_customer_rules import workflow_for


def test_workflow_auto_approve_default_on():
    wf = workflow_for("A123")
    assert wf.get("auto_approve") is True
    wf2 = workflow_for("A116")
    assert wf2.get("auto_approve") is True


def test_evaluate_auto_review_missing_requires_human(monkeypatch):
    from eng_review_service import evaluate_auto_review

    class FakeBom:
        id = 1
        is_active = True
        internal_code = "A123"
        model_code = "120-TEST"
        purchase_no = "PO1"
        eng_review_status = "pending_review"

    class FakeQ:
        def filter(self, *a, **k):
            return self

        def first(self):
            return FakeBom()

    class FakeDB:
        def query(self, *a, **k):
            return FakeQ()

    def fake_dossier(db, bom_id):
        return {
            "checklist": [
                {"label": "BOM 料单", "ready": True, "optional": False},
                {"label": "贴片坐标", "ready": False, "optional": False},
                {"label": "贴装类型", "ready": False, "optional": False},
            ],
            "checklist_policy": {"placement": True, "placement_waived": False},
        }

    monkeypatch.setattr("eng_review_service.build_review_dossier", fake_dossier)
    monkeypatch.setattr("eng_review_service._find_assets", lambda db, bom: (None, None, None))
    ev = evaluate_auto_review(FakeDB(), 1)
    assert ev["ok"] is False
    assert "贴片坐标" in ev["missing"]
