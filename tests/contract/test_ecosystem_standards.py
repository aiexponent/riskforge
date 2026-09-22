"""Contract tests for open-source ecosystem standards (PRD-187).

Verifies Dependabot configuration, README flat-square badge styling with brand teal (#0D5463),
reciprocal 5-tool ecosystem footer cross-linking, and absence of deprecated organization URLs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dependabot_configuration() -> None:
    """Ensure .github/dependabot.yml exists and defines weekly pip and github-actions scans."""
    dependabot_path = REPO_ROOT / ".github" / "dependabot.yml"
    assert dependabot_path.is_file(), ".github/dependabot.yml does not exist"

    data = yaml.safe_load(dependabot_path.read_text(encoding="utf-8"))
    assert data.get("version") == 2, f"Expected dependabot version 2, got {data.get('version')}"

    updates = data.get("updates", [])
    ecosystems = {u.get("package-ecosystem"): u for u in updates}

    assert "pip" in ecosystems, "Missing 'pip' package-ecosystem in dependabot.yml"
    assert (
        "github-actions" in ecosystems
    ), "Missing 'github-actions' package-ecosystem in dependabot.yml"

    assert ecosystems["pip"].get("schedule", {}).get("interval") == "weekly"
    assert ecosystems["github-actions"].get("schedule", {}).get("interval") == "weekly"


def test_readme_badges_and_reciprocal_ecosystem_footer() -> None:
    """Ensure README badges use flat-square and footer contains 5-tool reciprocal links."""
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.is_file(), "README.md does not exist"

    content = readme_path.read_text(encoding="utf-8")
    assert "style=flat-square" in content, "README badges must use style=flat-square"
    assert "0D5463" in content, "README badges must use brand teal #0D5463"

    sibling_tools = [
        "litmusai",
        "license-compliance-checker",
        "rag-benchmarking",
        "riskforge",
        "agentic-document-analyser",
    ]
    for tool in sibling_tools:
        assert tool in content, f"Missing tool '{tool}' in README reciprocal ecosystem"

    expected_links = [
        "https://github.com/aiexponent/litmusai",
        "https://github.com/aiexponent/license-compliance-checker",
        "https://github.com/aiexponent/rag-benchmarking",
        "https://github.com/aiexponent/agentic-document-analyser",
    ]
    for link in expected_links:
        assert link in content, f"Missing reciprocal link '{link}' in README.md"

    assert '<a href="https://aiexponent.com">aiexponent.com</a>' in content
    assert "aiexponenthq" not in content, "Deprecated 'aiexponenthq' found in README.md"
