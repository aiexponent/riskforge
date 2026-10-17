"""Regulatory-claims gate (B6): forbid known-wrong legal citations in public docs.

RiskForge makes EU AI Act, NIST, ISO, and US state-law claims on public surfaces.
This test locks the corrected citations so a regression cannot reintroduce a wrong
one. Scope is the public documentation (README, CONTRIBUTING, SECURITY and docs/), not the changelog, which
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
    "addressed by TraceForge": "Post-market monitoring is planned for a Sigil module, not TraceForge.",
    "via the TraceForge integration adapter": "Post-market monitoring is planned for a Sigil module.",
    "DISC-001": "Discrimination question ids are DI-001 to DI-004.",
    "value is a GPG key identifier": "export --sign takes an Ed25519 key file since 2.0.0.",
    "auto-adds `.riskforge/` to `.gitignore`": "init warns; it never edits .gitignore.",
    "adds this to `.gitignore` automatically": "init warns; it never edits .gitignore.",
    "Store the `.riskforge/` directory": "Never advise committing .riskforge/: it holds the assessment.",
    "can merge their YAML changes": "Merging two branches' audit logs breaks the chain.",
    "byte-identical to one generated in August": "Exports carry ids and timestamps; lockfiles pin dependencies.",
    "(`keyring`)": "keyring was removed in 2.0.0.",
    "riskforge serve": "The experimental server was removed in 2.0.0.",
    "pending publication in the Official Journal": "Regulation (EU) 2026/1744 was published on 24 July 2026.",
    "Article 9(2)(e)": "Article 9(2) has points (a) to (d) only.",
    "Annex IV(2)(g) sub-section on the risk management system": "Annex IV point 5 is the risk management system.",
    "Annex IV(2)(g)** requires": "Annex IV point 5 is the risk management system; point 2(g) is testing.",
    "conformity safeguards": "Article 60 sets conditions for real-world testing, not conformity safeguards.",
}


def _doc_files() -> list[Path]:
    """Git-tracked public Markdown: README, CONTRIBUTING, SECURITY and docs/.

    Uses git rather than a filesystem glob so gitignored internal notes (e.g.
    docs/internal/) that may reference a superseded value are never scanned.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "ls-files",
                "README.md",
                "CONTRIBUTING.md",
                "SECURITY.md",
                "docs/",
            ],
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
