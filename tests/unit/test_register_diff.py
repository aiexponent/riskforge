"""diff_registers reports added, removed and changed items field by field (PRD-343)."""

from __future__ import annotations

import copy

from riskforge.engine.diff import (
    FieldChange,
    RegisterDiff,
    diff_registers,
    fields_absent_from_schema,
)


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
        "risk_band": "medium",
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
    item.update(likelihood=5, risk_score=15, risk_band="high", description="new text")
    item["accepted"] = True
    item["mitigations"] = [{"description": "control", "status": "implemented"}]
    result = diff_registers(old, new)
    assert [change.item_id for change in result.changed] == [item["id"]]
    fields = {change.field: (change.old, change.new) for change in result.changed[0].changes}
    assert fields["likelihood"] == (3, 5)
    assert fields["risk_score"] == (9, 15)
    assert fields["accepted"] == (False, True)
    assert fields["description"] == ("d", "new text")
    assert fields["mitigations"] == (0, 1)
    assert fields["risk_band"] == ("medium", "high")
    assert result.added == [] and result.removed == []


MITIGATION_ID = "c" * 8 + "-0000-0000-0000-000000000003"


def _with_mitigation(register: dict) -> dict:
    register["items"][0]["mitigations"] = [
        {
            "id": MITIGATION_ID,
            "description": "control",
            "control_type": "preventive",
            "owner": "ML team",
            "status": "planned",
            "evidence_refs": [],
            "article_ref": "",
        }
    ]
    return register


def _changes(old: dict, new: dict) -> list[FieldChange]:
    result = diff_registers(old, new)
    assert len(result.changed) == 1, result
    return result.changed[0].changes


def test_an_edited_mitigation_names_the_field_even_with_the_same_count() -> None:
    old = _with_mitigation(_register())
    new = copy.deepcopy(old)
    new["items"][0]["mitigations"][0]["status"] = "implemented"
    assert _changes(old, new) == [
        FieldChange("mitigation cccccccc status", "planned", "implemented")
    ]


def test_mitigation_evidence_refs_and_article_ref_are_compared() -> None:
    old = _with_mitigation(_register())
    new = copy.deepcopy(old)
    new["items"][0]["mitigations"][0]["evidence_refs"] = ["evidence/parity-report.pdf"]
    new["items"][0]["mitigations"][0]["article_ref"] = "Art.9(2)(d)"
    assert _changes(old, new) == [
        FieldChange("mitigation cccccccc evidence_refs", [], ["evidence/parity-report.pdf"]),
        FieldChange("mitigation cccccccc article_ref", "", "Art.9(2)(d)"),
    ]


def test_accepted_by_is_compared() -> None:
    old = _register()
    new = copy.deepcopy(old)
    new["items"][0]["accepted_by"] = "Jane Doe, Head of AI"
    assert _changes(old, new) == [FieldChange("accepted_by", None, "Jane Doe, Head of AI")]


def test_article_refs_and_knowledge_gap_reason_are_compared() -> None:
    old = _register()
    old["items"][0]["article_refs"] = ["Art.9(2)(a)"]
    old["items"][0]["knowledge_gap_reason"] = ""
    new = copy.deepcopy(old)
    new["items"][0]["article_refs"] = ["Art.9(2)(a)", "Art.14"]
    new["items"][0]["knowledge_gap_reason"] = "No subgroup data yet"
    assert _changes(old, new) == [
        FieldChange("article_refs", ["Art.9(2)(a)"], ["Art.9(2)(a)", "Art.14"]),
        FieldChange("knowledge_gap_reason", "", "No subgroup data yet"),
    ]


def test_every_item_field_is_compared_in_file_order() -> None:
    old = _register()
    old["items"][0].update(regulatory_status="settled", source="manual", notes="")
    new = copy.deepcopy(old)
    new["items"][0].update(
        notes="n", source="pattern", regulatory_status="pending_implementing_act"
    )
    assert [change.field for change in _changes(old, new)] == [
        "regulatory_status",
        "source",
        "notes",
    ]


def test_an_absent_field_equals_none() -> None:
    old = _with_mitigation(_register())
    new = copy.deepcopy(old)
    new["items"][0]["accepted_by"] = None
    new["items"][0]["mitigations"][0]["recorded_by"] = None
    assert diff_registers(old, new) == RegisterDiff()


def test_fields_a_1_0_0_export_cannot_hold_are_skipped_against_one() -> None:
    old = _with_mitigation(_register())
    new = copy.deepcopy(old)
    new["items"][0]["accepted_by"] = "Jane Doe, Head of AI"
    new["items"][0]["mitigations"][0]["recorded_by"] = "Jane Doe, Head of AI"
    ignore = fields_absent_from_schema("1.0.0")
    assert diff_registers(old, new, ignore=ignore) == RegisterDiff()
    assert fields_absent_from_schema("1.1.0") == frozenset()


def test_mitigations_added_and_removed_are_named() -> None:
    old = _with_mitigation(_register())
    new = copy.deepcopy(old)
    added = dict(old["items"][0]["mitigations"][0], id="d" * 8 + "-0000-0000-0000-000000000004")
    new["items"][0]["mitigations"] = [added]
    assert _changes(old, new) == [
        FieldChange("mitigation dddddddd", None, "control"),
        FieldChange("mitigation cccccccc", "control", None),
    ]


def test_a_system_block_change_is_a_register_change() -> None:
    old = _register()
    old["system"] = {"id": "s", "name": "X", "purpose": "credit scoring", "inputs": ["a"]}
    new = copy.deepcopy(old)
    new["system"]["purpose"] = "credit scoring for loans"
    new["system"]["inputs"] = ["a", "b"]
    result = diff_registers(old, new)
    assert result.changed == []
    assert result.register_changes == [
        FieldChange("system.purpose", "credit scoring", "credit scoring for loans"),
        FieldChange("system.inputs", ["a"], ["a", "b"]),
    ]


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
