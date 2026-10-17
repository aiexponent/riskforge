"""User-facing text carries no em-dashes (house style; issue #52).

The public docs also avoid the house word list and name no internal ticket ids.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src" / "riskforge"
# storage/ is scanned because FileStore logs audit-chain failures to stderr.
SCANNED_PATHS = [SRC / "cli", SRC / "exporters", SRC / "_data", SRC / "storage"]
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
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


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
    pattern = re.compile(r"\b(" + "|".join(re.escape(word) for word in AVOID) + r")\b", re.I)
    hits = []
    for path in _public_docs():
        prose = CODE.sub(lambda m: "\n" * m.group(0).count("\n"), path.read_text(encoding="utf-8"))
        for number, line in enumerate(prose.splitlines(), start=1):
            hits += [
                f"{path.relative_to(REPO)}:{number}: {m.group(0)}" for m in pattern.finditer(line)
            ]
    assert hits == [], "avoid-list words found:\n" + "\n".join(hits)


INTERNAL_TICKET = re.compile(r"\bPRD-\d+")


def test_public_docs_name_no_internal_tickets() -> None:
    hits = [
        f"{path.relative_to(REPO)}:{number}: {m.group(0)}"
        for path in _public_docs()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for m in INTERNAL_TICKET.finditer(line)
    ]
    assert hits == [], "internal ticket ids found:\n" + "\n".join(hits)
