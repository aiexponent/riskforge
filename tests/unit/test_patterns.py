"""Bundled patterns name their high-risk route and match purpose phrases (PRD-335)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import riskforge._data as data_pkg
from riskforge.engine.assess import AssessEngine, keyword_matches

ENGINE = AssessEngine(Path(data_pkg.__file__).parent)
POINT_CATEGORY = {
    1: "biometric",
    2: "critical_infrastructure",
    3: "education",
    4: "employment",
    5: "essential_services",
    6: "law_enforcement",
    7: "migration",
    8: "justice",
}
CV_SCREENING_PURPOSE = (
    "Automated resume screening and candidate ranking for hiring decisions in recruitment."
)


def _ids(category: str, purpose: str) -> list[str]:
    return [p["pattern_id"] for p in ENGINE.match_patterns(category, purpose)]


def test_the_library_has_the_seven_patterns() -> None:
    assert sorted(p["pattern_id"] for p in ENGINE.load_patterns()) == [
        "CREDIT_SCORING_BIAS",
        "CRIMINAL_RISK_ASSESSMENT",
        "EDUCATION_ASSESSMENT",
        "HIRING_SCREENING",
        "LAW_ENFORCEMENT_BIOMETRIC",
        "MEDICAL_DIAGNOSIS",
        "MIGRATION_ASYLUM",
    ]


def test_every_pattern_names_its_high_risk_route() -> None:
    for pattern in ENGINE.load_patterns():
        if pattern.get("high_risk_route") == "annex_i":
            assert pattern["article_6_ref"] == "Art.6(1)", pattern["pattern_id"]
            assert pattern["annex_i_legislation"], pattern["pattern_id"]
            assert pattern["triggers"]["annex_iii_categories"] == [], pattern["pattern_id"]
            continue
        point = pattern["annex_iii_point"]
        assert re.fullmatch(r"[1-8]\([a-e]\)", point), pattern["pattern_id"]
        assert POINT_CATEGORY[int(point[0])] in pattern["triggers"]["annex_iii_categories"]


def test_medical_pattern_takes_the_annex_i_route() -> None:
    medical = next(p for p in ENGINE.load_patterns() if p["pattern_id"] == "MEDICAL_DIAGNOSIS")
    assert medical["high_risk_route"] == "annex_i"
    assert "annex_iii_point" not in medical
    legislation = " ".join(medical["annex_i_legislation"])
    assert "Regulation (EU) 2017/745" in legislation
    assert "Regulation (EU) 2017/746" in legislation


@pytest.mark.parametrize(
    "purpose",
    [
        "Diagnostic support for chest radiology images",
        "Supports medical diagnosis of skin lesions",
        "In vitro diagnostic analysis of blood samples",
        "Clinical prognosis for sepsis patients",
    ],
)
def test_medical_pattern_matches_without_an_annex_iii_category(purpose: str) -> None:
    assert _ids("", purpose) == ["MEDICAL_DIAGNOSIS"]


@pytest.mark.parametrize(
    "purpose",
    [
        "Vehicle engine diagnostics assistant",
        "Network fault diagnosis for telecom routers",
        "Sales prognosis dashboard",
    ],
)
def test_non_medical_diagnosis_is_not_medical_diagnosis(purpose: str) -> None:
    assert _ids("", purpose) == []


def test_patient_scheduling_is_not_medical_diagnosis() -> None:
    assert _ids("", "Patient appointment scheduling for clinics") == []


def test_cv_screening_is_not_medical_diagnosis() -> None:
    assert _ids("employment", CV_SCREENING_PURPOSE) == ["HIRING_SCREENING"]
    assert _ids("", CV_SCREENING_PURPOSE) == []


def test_annex_iii_patterns_need_their_category() -> None:
    assert _ids("", "Credit scoring for consumer loans") == []


@pytest.mark.parametrize(
    ("keyword", "purpose", "expected"),
    [
        ("credit", "Creditworthiness assessment for consumer loans", True),
        ("facial recognition", "Facial recognition of travellers", True),
        ("facial recognition", "Real-time facial-recognition at border crossings", True),
        ("cv", "Ranks CVs, for hiring.", True),
        ("test", "Online contest entry screening", False),
        ("credit", "Accredited training providers", False),
        ("facial recognition", "Facial expression recognition", False),
        ("re-offending", "Predicts re-offending risk for police case reviews", True),
    ],
)
def test_keyword_matching(keyword: str, purpose: str, expected: bool) -> None:
    assert keyword_matches(keyword, purpose) is expected


def test_multi_word_trigger_selects_the_biometric_pattern() -> None:
    assert _ids("biometric", "Facial recognition of travellers") == ["LAW_ENFORCEMENT_BIOMETRIC"]


def test_creditworthiness_selects_the_credit_pattern() -> None:
    assert _ids("essential_services", "Creditworthiness assessment for retail customers") == [
        "CREDIT_SCORING_BIAS"
    ]


def test_reoffending_selects_the_criminal_risk_pattern() -> None:
    assert _ids("law_enforcement", "Scores the risk of re-offending for police case reviews") == [
        "CRIMINAL_RISK_ASSESSMENT"
    ]


def test_insurance_pricing_does_not_get_the_credit_pattern() -> None:
    assert _ids("essential_services", "Life insurance pricing") == []


def test_exam_scheduling_does_not_get_the_education_pattern() -> None:
    assert _ids("education", "Exam scheduling and timetabling") == []


def test_essay_marking_selects_the_education_pattern() -> None:
    assert _ids("education", "Automated essay marking") == ["EDUCATION_ASSESSMENT"]
