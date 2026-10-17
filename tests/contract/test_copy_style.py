"""User-facing text carries no em-dashes (house style; issue #52).

The public docs also avoid the house word list and name no internal ticket ids.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "riskforge"
# storage/ is scanned because FileStore logs audit-chain failures to stderr.
SCANNED_PATHS = [
    SRC / "cli",
    SRC / "exporters",
    SRC / "_data",
    SRC / "storage",
    SRC / "api.py",
    REPO / "docs" / "library-api.md",
]
SUFFIXES = {".py", ".html", ".css", ".yaml", ".json", ".md"}
EM_DASH = chr(0x2014)


def _hits(paths: list[Path]) -> list[str]:
    hits = []
    for root in paths:
        assert root.exists(), root
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in files:
            if path.is_file() and path.suffix in SUFFIXES:
                text = path.read_text(encoding="utf-8")
                for number, line in enumerate(text.splitlines(), start=1):
                    if EM_DASH in line:
                        hits.append(f"{path.relative_to(REPO)}:{number}")
    return hits


def test_no_em_dashes_in_user_facing_source() -> None:
    hits = _hits(SCANNED_PATHS)
    assert hits == [], "em-dashes found:\n" + "\n".join(hits)


AVOID = (
    "delve", "leverage", "seamless", "seamlessly", "robust", "underscore", "testament",
    "tapestry", "realm", "navigate", "pivotal", "harness", "unlock", "elevate", "embark",
    "intricate", "multifaceted", "holistic", "myriad", "plethora", "paradigm", "synergy",
    "game-changer", "cutting-edge", "ever-evolving", "fast-paced", "utilize",
    "groundbreaking", "unparalleled", "meticulous",
)  # fmt: skip
DOC_PATHS = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/",
    "examples/README.md",
    "benchmarks/README.md",
]
# Code is not prose: a keyword such as `unlock` in a pattern's exclude list is data.
# Mermaid diagrams are prose (their labels are read as text), so they are scanned, and
# so is a backticked phrase; only a backticked single word or identifier is skipped.
CODE = re.compile(r"^```(?!mermaid\b)[^\n]*\n.*?^```|`[^`\s]+`", re.S | re.M)


def _forms(word: str) -> list[str]:
    """``word`` and its inflections: leverage, leverages, leveraged, leveraging."""
    if word.endswith("e"):
        return [word, word + "s", word + "d", word[:-1] + "ing"]
    return [word, word + "s", word + "es", word + "ed", word + "ing", word + "ly"]


AVOID_WORDS = re.compile(
    r"\b(" + "|".join(re.escape(form) for word in AVOID for form in _forms(word)) + r")\b",
    re.I,
)


def _avoid_hits(text: str) -> list[tuple[int, str]]:
    """(line number, word) for every avoid-list word in the prose of Markdown ``text``."""
    prose = CODE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return [
        (number, m.group(0))
        for number, line in enumerate(prose.splitlines(), start=1)
        for m in AVOID_WORDS.finditer(line)
    ]


def _public_docs() -> list[Path]:
    """Git-tracked public Markdown. CHANGELOG.md keeps its history as written."""
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", *DOC_PATHS],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO / line for line in out.splitlines() if line.endswith(".md")]


def test_no_em_dashes_in_public_docs() -> None:
    docs = _public_docs()
    assert docs, "no public docs found"
    hits = _hits(docs)
    assert hits == [], "em-dashes found:\n" + "\n".join(hits)


def test_public_docs_avoid_the_house_word_list() -> None:
    hits = [
        f"{path.relative_to(REPO)}:{number}: {word}"
        for path in _public_docs()
        for number, word in _avoid_hits(path.read_text(encoding="utf-8"))
    ]
    assert hits == [], "avoid-list words found:\n" + "\n".join(hits)


@pytest.mark.parametrize(
    "text",
    [
        "Teams are leveraging the register.",
        "It delves into the chain.",
        "The export navigated every check.",
        "```mermaid\nflowchart LR\n  A[Seamless export] --> B\n```\n",
        "Use `a robust check` here.",
    ],
)
def test_word_list_check_catches(text: str) -> None:
    assert _avoid_hits(text), text


@pytest.mark.parametrize(
    "text",
    [
        "The tests measure robustness.",
        "A pattern lists `unlock` in `triggers.exclude_keywords`.",
        "```yaml\nexclude_keywords: [unlock]\n```\n",
    ],
)
def test_word_list_check_allows(text: str) -> None:
    assert _avoid_hits(text) == [], text


INTERNAL_TICKET = re.compile(r"\bPRD-\d+")


def test_public_docs_name_no_internal_tickets() -> None:
    hits = [
        f"{path.relative_to(REPO)}:{number}: {m.group(0)}"
        for path in _public_docs()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for m in INTERNAL_TICKET.finditer(line)
    ]
    assert hits == [], "internal ticket ids found:\n" + "\n".join(hits)
