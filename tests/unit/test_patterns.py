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
# Every risk title the 1.1.3 patterns shipped. assess matches a register item to its
# pattern risk by pattern id and title, so renaming one would add a duplicate item
# when a 1.1.3 project is assessed again.
KEPT_PATTERN_TITLES = {
    ("CREDIT_SCORING_BIAS", "Demographic bias in credit scoring outputs"),
    ("CREDIT_SCORING_BIAS", "Lack of explanation for credit decisions"),
    ("HIRING_SCREENING", "Proxy discrimination in automated CV screening"),
    ("HIRING_SCREENING", "Lack of explainability for rejection decisions"),
    ("HIRING_SCREENING", "Automation bias in recruiter review of shortlisted candidates"),
    ("LAW_ENFORCEMENT_BIOMETRIC", "Chilling effect on freedom of assembly and expression"),
    (
        "LAW_ENFORCEMENT_BIOMETRIC",
        "Higher false match rates for under-represented demographic groups",
    ),
    ("EDUCATION_ASSESSMENT", "Bias in automated educational assessment"),
    ("EDUCATION_ASSESSMENT", "Students unable to understand or contest automated grade decisions"),
    ("MEDICAL_DIAGNOSIS", "False negatives in medical screening causing delayed treatment"),
    ("MEDICAL_DIAGNOSIS", "Clinician over-reliance on AI diagnostic suggestions"),
    ("MIGRATION_ASYLUM", "AI-assisted asylum decisions affecting right to protection"),
    ("MIGRATION_ASYLUM", "Applicants unable to understand factors influencing their assessment"),
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


def test_every_1_1_3_pattern_risk_title_is_kept() -> None:
    current = {
        (pattern["pattern_id"], risk["title"])
        for pattern in ENGINE.load_patterns()
        for risk in pattern["risks"]
    }
    assert KEPT_PATTERN_TITLES - current == set()


@pytest.mark.parametrize(
    ("keyword", "purpose", "expected"),
    [
        ("credit", "Évaluation du crédit à la consommation", True),
        ("loan", "Réseau éloan interne", False),
        ("facial recognition", "FACIAL RECOGNITION at gates", True),
        ("strasse", "Adressen in der Hauptstraße", False),
        ("strasse", "Straße names", True),
    ],
)
def test_keyword_matching_folds_accents_and_case(
    keyword: str, purpose: str, expected: bool
) -> None:
    assert keyword_matches(keyword, purpose) is expected


ALL_CATEGORIES = ["", *POINT_CATEGORY.values()]


@pytest.mark.parametrize(
    ("purpose", "wrong_pattern"),
    [
        ("Detects credit card fraud in real-time card payments", "CREDIT_SCORING_BIAS"),
        ("Life insurance underwriting for individual applicants", "CREDIT_SCORING_BIAS"),
        ("Facial recognition unlocks the owner's own phone", "LAW_ENFORCEMENT_BIOMETRIC"),
        ("Biometric face unlock for the user's own phone", "LAW_ENFORCEMENT_BIOMETRIC"),
        ("Licence plate identification for car park barriers", "LAW_ENFORCEMENT_BIOMETRIC"),
        (
            "Matching licence plates against a permit list to open car park barriers",
            "LAW_ENFORCEMENT_BIOMETRIC",
        ),
        ("Interview room booking for the HR team", "HIRING_SCREENING"),
        ("Border queue wait-time display at airport passport control", "MIGRATION_ASYLUM"),
        ("Engine control unit diagnoses faults in vehicle engines", "MEDICAL_DIAGNOSIS"),
    ],
)
def test_purpose_outside_the_pattern_does_not_get_it(purpose: str, wrong_pattern: str) -> None:
    for category in ALL_CATEGORIES:
        assert wrong_pattern not in _ids(category, purpose), category


@pytest.mark.parametrize(
    ("category", "purpose", "expected"),
    [
        (
            "essential_services",
            "Creditworthiness scoring for consumer loans",
            "CREDIT_SCORING_BIAS",
        ),
        ("essential_services", "Credit risk decisions on card applications", "CREDIT_SCORING_BIAS"),
        ("employment", "CV screening for job applicants", "HIRING_SCREENING"),
        ("employment", "Scores recorded job interviews of graduates", "HIRING_SCREENING"),
        (
            "biometric",
            "Facial recognition to identify people in a crowd",
            "LAW_ENFORCEMENT_BIOMETRIC",
        ),
        (
            "law_enforcement",
            "Face matching of CCTV stills against a watchlist",
            "LAW_ENFORCEMENT_BIOMETRIC",
        ),
        ("migration", "Visa application triage for consular officers", "MIGRATION_ASYLUM"),
        ("", "Medical diagnosis support for radiology", "MEDICAL_DIAGNOSIS"),
    ],
)
def test_purpose_the_pattern_covers_still_gets_it(
    category: str, purpose: str, expected: str
) -> None:
    assert _ids(category, purpose) == [expected]


def test_an_exclude_keyword_skips_the_pattern(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    patterns_dir.mkdir()
    (patterns_dir / "patterns.yaml").write_text(
        'schema_version: "1.1.0"\n'
        "patterns:\n"
        "  - pattern_id: P\n"
        "    triggers:\n"
        "      annex_iii_categories: [biometric]\n"
        '      purpose_keywords: ["face recognition"]\n'
        '      exclude_keywords: ["unlock"]\n',
        encoding="utf-8",
    )
    engine = AssessEngine(tmp_path)
    assert [p["pattern_id"] for p in engine.match_patterns("biometric", "Face recognition")] == [
        "P"
    ]
    assert engine.match_patterns("biometric", "Face recognition unlocks a phone") == []


@pytest.mark.parametrize("version", ["1.0.0", None])
def test_load_patterns_refuses_another_schema_version(tmp_path: Path, version: str | None) -> None:
    patterns_dir = tmp_path / "patterns"
    patterns_dir.mkdir()
    header = f'schema_version: "{version}"\n' if version else ""
    (patterns_dir / "patterns.yaml").write_text(header + "patterns: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"schema_version.*1\.1\.0"):
        AssessEngine(tmp_path).load_patterns()


def test_load_patterns_reads_schema_1_1_0(tmp_path: Path) -> None:
    patterns_dir = tmp_path / "patterns"
    patterns_dir.mkdir()
    (patterns_dir / "patterns.yaml").write_text(
        'schema_version: "1.1.0"\npatterns: []\n', encoding="utf-8"
    )
    assert AssessEngine(tmp_path).load_patterns() == []
