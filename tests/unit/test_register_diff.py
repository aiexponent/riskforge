"""diff_registers reports added, removed and changed items field by field (PRD-343)."""

from __future__ import annotations

import copy

from riskforge.engine.diff import FieldChange, RegisterDiff, diff_registers


def _register() -> dict:
    item = {
        "id": "a" * 8 + "-0000-0000-0000-000000000001",
        "title": "Bias",
        "description": "d",
        "dimension": "discrimination",
        "likelihood": 3,
        "severity": 3,
        "risk_score": 9,
        "residual_likelihood": 2,
        "residual_severity": 3,
        "residual_risk_score": 6,
        "accepted": False,
        "acceptance_rationale": "",
        "knowledge_gap": False,
        "mitigations": [],
    }
    return {"risk_appetite_threshold": 9, "items": [item]}


def test_score_text_and_mitigation_changes_are_reported() -> None:
    old = _register()
    new = copy.deepcopy(old)
    item = new["items"][0]
    item.update(likelihood=5, risk_score=15, description="new text", accepted=True)
    item["mitigations"] = [{"description": "control", "status": "implemented"}]
    result = diff_registers(old, new)
    assert [change.item_id for change in result.changed] == [item["id"]]
    fields = {change.field: (change.old, change.new) for change in result.changed[0].changes}
    assert fields["likelihood"] == (3, 5)
    assert fields["risk_score"] == (9, 15)
    assert fields["accepted"] == (False, True)
    assert fields["description"] == ("d", "new text")
    assert fields["mitigations"] == (0, 1)
    assert result.added == [] and result.removed == []


def test_an_edited_mitigation_is_a_change_even_with_the_same_count() -> None:
    old = _register()
    old["items"][0]["mitigations"] = [{"description": "control", "status": "planned"}]
    new = copy.deepcopy(old)
    new["items"][0]["mitigations"][0]["status"] = "implemented"
    result = diff_registers(old, new)
    assert result.changed[0].changes == [FieldChange("mitigations", 1, 1)]


def test_fields_outside_the_compared_set_are_ignored() -> None:
    old = _register()
    new = copy.deepcopy(old)
    new["items"][0]["identified_at"] = "2026-10-15T00:00:00Z"
    new["items"][0]["mitigations"] = [{"description": "", "status": "", "recorded_by": "A, B"}]
    old["items"][0]["mitigations"] = [{"description": "", "status": ""}]
    assert diff_registers(old, new) == RegisterDiff()


def test_added_removed_and_threshold() -> None:
    old = _register()
    new = copy.deepcopy(old)
    new["items"][0]["id"] = "b" * 8 + "-0000-0000-0000-000000000002"
    new["risk_appetite_threshold"] = 12
    result = diff_registers(old, new)
    assert [i["id"][:8] for i in result.added] == ["b" * 8]
    assert [i["id"][:8] for i in result.removed] == ["a" * 8]
    assert result.changed == []
    assert result.register_changes == [FieldChange("risk_appetite_threshold", 9, 12)]


def test_identical_registers_have_no_changes() -> None:
    assert diff_registers(_register(), _register()) == RegisterDiff()
