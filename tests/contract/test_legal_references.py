"""Legal-references gate: every reference in src/ must be on the checked list.

RiskForge output goes to auditors and regulators (AGENTS.md hard rule 4), so each
article, annex, NIST AI RMF subcategory and ISO/IEC 42001 item that the package
ships has been checked against its source. The checked list lives in
``legal_references.yaml`` next to this file, with the source URL for every entry.

The test extracts references from every text file under ``src/`` with regular
expressions and fails on any reference that is not on the list. Adding a new
reference therefore means checking it against the official text and listing it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src" / "riskforge"
CHECKED_LIST = Path(__file__).with_name("legal_references.yaml")
PATTERNS_FILE = SRC_DIR / "_data" / "patterns" / "patterns.yaml"

TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".html", ".css", ".md", ".txt", ".j2"}

# One article number with its paragraphs and points: 9, 4a(1), 6(1c), 13(3)(b)(iv).
_GROUPS = r"(?:\((?:\d+[a-z]?|[a-z]+)\))"
_NUM = rf"\d+[a-z]?{_GROUPS}*"
# A later item may leave out the article: "Article 9(6) and (8)", "Art.9(2)(a) and (b)".
_ITEM = rf"(?:{_NUM}|{_GROUPS}+)"
_ARTICLE = re.compile(
    rf"\b(?:Art\.\s?|Articles?\s)(?P<head>{_NUM})"
    rf"(?P<tail>(?:(?:,\s|\s(?:and|or|to)\s){_ITEM})*)"
)
_TAIL_ITEM = re.compile(_ITEM)
_ARTICLE_NUMBER = re.compile(r"\d+[a-z]?")
_PARAGRAPH = re.compile(r"\d+[a-z]?\(\d+[a-z]?\)")


def _resolve(item: str, head: str) -> str:
    """Complete an item without an article number from the reference before it.

    "(8)" after "9(6)" is a paragraph, so "9(8)"; "(b)" after "9(2)(a)" is a point,
    so "9(2)(b)".
    """
    if item[0].isdigit():
        return item
    paragraph = _PARAGRAPH.match(head)
    if item[1].isalpha() and paragraph:
        return paragraph.group() + item
    number = _ARTICLE_NUMBER.match(head)
    return (number.group() if number else head) + item


_OTHER = [
    re.compile(r"\bAnnex [IVX]+\b(?:,? Section [A-Z])?(?:,? point \d+[a-z]?(?:\([a-z]\))?)?"),
    re.compile(r"\bAnnex A\.\d+\b"),
    re.compile(r"\bClause \d+(?:\.\d+)*\b"),
    re.compile(r"\b(?:GOVERN|MAP|MEASURE|MANAGE) \d+\.\d+\b"),
    re.compile(r"\bRegulation \(EU\) \d{4}/\d+\b"),
    re.compile(r"\bRecital \d+\b"),
]

# References that were corrected in PRD-368 and must not come back.
FORBIDDEN = {
    "Art.9(7)": "Art.9(7) only permits real-world testing under Article 60; metric and "
    "threshold tests cite Art.9(8).",
    "Art.10(5)": "Regulation (EU) 2026/1744 deleted Art.10(5); special categories of "
    "personal data for bias detection are now Art.4a(1).",
}
_CLAUSE_ANNEX_LABEL = re.compile(r"\bClause A\.\d+")


def _source_files() -> list[Path]:
    return sorted(
        p
        for p in SRC_DIR.rglob("*")
        if p.is_file() and p.suffix in TEXT_SUFFIXES and "__pycache__" not in p.parts
    )


def _instrument_prefix(text: str, start: int, end: int) -> str:
    """Qualify GDPR and Charter articles so they do not collide with AI Act ones."""
    if text[max(0, start - 5) : start] == "GDPR ":
        return "GDPR "
    if text[end : end + 15] == " of the Charter":
        return "Charter "
    return ""


def extract_references(text: str) -> Iterator[str]:
    """Yield every reference in *text*, normalised to the repo's ``Art.9(8)`` style."""
    for match in _ARTICLE.finditer(text):
        prefix = _instrument_prefix(text, match.start(), match.end())
        previous = match.group("head")
        yield f"{prefix}Art.{previous}"
        for item in _TAIL_ITEM.findall(match.group("tail")):
            previous = _resolve(item, previous)
            yield f"{prefix}Art.{previous}"
    for pattern in _OTHER:
        for match in pattern.finditer(text):
            yield re.sub(r",", "", match.group(0))


def _structured_references() -> Iterator[str]:
    """Annex III points stored as bare values (``annex_iii_point: "5(b)"``)."""
    data = yaml.safe_load(PATTERNS_FILE.read_text(encoding="utf-8"))
    for pattern in data.get("patterns", []):
        point = pattern.get("annex_iii_point")
        if point:
            yield f"Annex III point {point}"


def _found_references() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _source_files():
        rel = str(path.relative_to(REPO_ROOT))
        for ref in extract_references(path.read_text(encoding="utf-8")):
            found.setdefault(ref, []).append(rel)
    for ref in _structured_references():
        found.setdefault(ref, []).append(str(PATTERNS_FILE.relative_to(REPO_ROOT)))
    return found


def _checked_list() -> tuple[dict[str, dict], dict[str, dict]]:
    data = yaml.safe_load(CHECKED_LIST.read_text(encoding="utf-8"))
    return data["sources"], data["references"]


@pytest.fixture(scope="module")
def found() -> dict[str, list[str]]:
    if not SRC_DIR.exists():
        pytest.skip("legal-references gate runs from a source checkout")
    return _found_references()


def test_every_reference_in_src_is_checked(found: dict[str, list[str]]) -> None:
    _, references = _checked_list()
    unknown = {ref: files for ref, files in found.items() if ref not in references}
    lines = [f"{ref}: {sorted(set(files))}" for ref, files in sorted(unknown.items())]
    assert not unknown, (
        "References in src/ that are not on tests/contract/legal_references.yaml. "
        "Check each one against the official text, then add it with its source:\n"
        + "\n".join(lines)
    )


def test_checked_list_has_no_stale_entries(found: dict[str, list[str]]) -> None:
    _, references = _checked_list()
    stale = sorted(set(references) - set(found))
    assert not stale, f"Checked-list entries no longer used in src/, remove them: {stale}"


def test_every_entry_has_a_source_url() -> None:
    sources, references = _checked_list()
    for name, source in sources.items():
        assert str(source.get("url", "")).startswith(("http://", "https://")), name
    for ref, entry in references.items():
        assert entry.get("source") in sources, f"{ref}: unknown source {entry.get('source')!r}"
        assert entry.get("status") in {"verified", "unverified"}, ref


def test_corrected_references_do_not_return(found: dict[str, list[str]]) -> None:
    back = {ref: reason for ref, reason in FORBIDDEN.items() if ref in found}
    assert not back, back
    labels = [
        str(path.relative_to(REPO_ROOT))
        for path in _source_files()
        if _CLAUSE_ANNEX_LABEL.search(path.read_text(encoding="utf-8"))
    ]
    assert not labels, f"ISO/IEC 42001 Annex A items are 'Annex A.x', not 'Clause A.x': {labels}"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('article_refs: ["Art.9(2)(a)", "Art.13(3)(b)(iv)"]', ["Art.9(2)(a)", "Art.13(3)(b)(iv)"]),
        ("Article 9(6) to 9(8) Test Requirements", ["Art.9(6)", "Art.9(8)"]),
        ("Art.6(1a) to 6(1c)", ["Art.6(1a)", "Art.6(1c)"]),
        ("Article 9(6) and (8)", ["Art.9(6)", "Art.9(8)"]),
        ("Article 9(6) and (7)", ["Art.9(6)", "Art.9(7)"]),
        ("Art.9(2)(a) and (b)", ["Art.9(2)(a)", "Art.9(2)(b)"]),
        ("Article 26(1), (2) and (5)", ["Art.26(1)", "Art.26(2)", "Art.26(5)"]),
        (
            "GDPR Articles 13(2)(f), 14(2)(g) and 15(1)(h) require",
            ["GDPR Art.13(2)(f)", "GDPR Art.14(2)(g)", "GDPR Art.15(1)(h)"],
        ),
        ("Article 19(2) of the Charter of Fundamental Rights", ["Charter Art.19(2)"]),
        ("(Annex I, Section A, point 11)", ["Annex I Section A point 11"]),
        ('nist_rmf_ref: "MEASURE 2.11"', ["MEASURE 2.11"]),
        ('iso42001_ref: "Annex A.7"', ["Annex A.7"]),
    ],
)
def test_extractor(text: str, expected: list[str]) -> None:
    assert list(extract_references(text)) == expected
