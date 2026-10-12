"""User-facing text carries no em-dashes (house style; issue #52, PRD-327)."""

from __future__ import annotations

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
