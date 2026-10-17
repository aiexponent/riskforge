"""Regulatory-claims gate (B6): forbid known-wrong legal citations in public docs.

RiskForge makes EU AI Act, NIST, ISO, and US state-law claims on public surfaces.
This test locks the corrected citations so a regression cannot reintroduce a wrong
one. Scope is the public documentation (README + docs/), not the changelog, which
may reference a superseded value when describing the correction itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Substring -> reason it must never appear in public documentation.
FORBIDDEN: dict[str, str] = {
    "HB 1709": "Texas bill that never became law; the enacted statute is HB 149 (TRAIGA).",
    "HB1709": "Texas bill that never became law; the enacted statute is HB 149 (TRAIGA).",
    "mathematically prove": "No tool proves compliance; RiskForge produces evidence.",
    "8 statutory risk dimensions": "The 8 dimensions are RiskForge's structure, not the statute's.",
    "Provisional Enforcement Deadline": "Superseded wording; the README states the dates as law.",
    "Signed PDF": "RiskForge signs the JSON export, not the PDF.",
    "Art. 9(10)<br/>Documentation": "Removed mapping; see docs/article-9-mapping.md.",
}


def _doc_files() -> list[Path]:
    """Git-tracked Markdown under README + docs/ (what actually ships publicly).

    Uses git rather than a filesystem glob so gitignored internal notes (e.g.
    docs/internal/) that may reference a superseded value are never scanned.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "README.md", "docs/"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    files = [REPO_ROOT / line for line in out.splitlines() if line.strip().endswith(".md")]
    return [f for f in files if f.exists()]


def test_no_forbidden_citations() -> None:
    if not (REPO_ROOT / "README.md").exists():
        pytest.skip("regulatory-claims gate runs from a source checkout")

    problems: list[str] = []
    for doc in _doc_files():
        text = " ".join(doc.read_text(encoding="utf-8").split())
        for bad, reason in FORBIDDEN.items():
            if bad in text:
                rel = doc.relative_to(REPO_ROOT)
                problems.append(f"{rel}: contains '{bad}' ({reason})")

    assert not problems, "Forbidden regulatory citations found:\n" + "\n".join(problems)
