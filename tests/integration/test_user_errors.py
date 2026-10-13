"""Common first-run mistakes get one line and exit 3, never a traceback (PRD-326)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rf_testkit import run_rf

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
REPO = Path(__file__).resolve().parents[2]
RAG_REPORT = REPO / "tests" / "fixtures" / "upstream" / "sample_rag_benchmarking_report.json"


def _init(project: Path) -> str:
    result = run_rf(
        [
            "init",
            "-n",
            "X",
            "-s",
            "1",
            "-p",
            "credit scoring for loans",
            "--provider",
            "P",
            "-c",
            "essential_services",
            "--project-dir",
            str(project),
        ]
    )
    assert result.returncode == 0, result.output
    return UUID_RE.search(result.output).group(0)


def _assess(project: Path, system_id: str) -> None:
    answers = project / "answers.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n  PR-001: { applies: yes, likelihood: 2, severity: 2 }\n"
    )
    result = run_rf(
        [
            "assess",
            system_id,
            "-a",
            "A",
            "-r",
            "B",
            "--answers",
            str(answers),
            "--project-dir",
            str(project),
        ]
    )
    assert result.returncode == 0, result.output


def _assert_clean(result, code: int, fragment: str, one_line: bool = True) -> None:
    """Exit *code*, *fragment* in the output, no traceback.

    With one_line, stderr holds exactly one line: the message from ``fail()``. Bad option
    values go through Click instead, which adds its usage line and boxes the message.
    """
    assert result.returncode == code, result.output
    assert fragment in result.output, result.output
    assert "Traceback" not in result.output, result.output
    if one_line:
        assert len(result.stderr.strip().splitlines()) == 1, result.stderr


def test_validate_without_a_project(tmp_path: Path) -> None:
    result = run_rf(["validate", "x", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "No RiskForge project")


def test_verify_without_a_project(tmp_path: Path) -> None:
    result = run_rf(["verify", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "No RiskForge project")


def test_init_with_unknown_category(tmp_path: Path) -> None:
    result = run_rf(
        [
            "init",
            "-n",
            "X",
            "-s",
            "1",
            "-p",
            "p",
            "--provider",
            "P",
            "-c",
            "credit",
            "--project-dir",
            str(tmp_path),
        ]
    )
    _assert_clean(result, 3, "not an Annex III category", one_line=False)
    assert not (tmp_path / "riskforge.yaml").exists()


def test_second_init(tmp_path: Path) -> None:
    _init(tmp_path)
    result = run_rf(
        ["init", "-n", "Y", "-s", "1", "-p", "p", "--provider", "P"]
        + ["--project-dir", str(tmp_path)]
    )
    _assert_clean(result, 3, "already exists")


@pytest.mark.parametrize(
    "command",
    [
        ["validate", "{sid}"],
        ["export", "{sid}"],
        ["risk", "list", "{sid}"],
        ["tests", "generate", "{sid}"],
        ["import", "{sid}", "-a", "rag-benchmarking", "-r", str(RAG_REPORT)],
    ],
)
def test_commands_before_assess(tmp_path: Path, command: list[str]) -> None:
    sid = _init(tmp_path)
    args = [part.replace("{sid}", sid) for part in command] + ["--project-dir", str(tmp_path)]
    _assert_clean(run_rf(args), 3, "has no risk register yet")


def test_unknown_system_id(tmp_path: Path) -> None:
    _init(tmp_path)
    result = run_rf(["system", "show", "deadbeef", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "No system 'deadbeef'")


def test_unknown_adapter(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    result = run_rf(
        ["import", sid, "-a", "ragbench", "-r", str(RAG_REPORT), "--project-dir", str(tmp_path)]
    )
    _assert_clean(result, 3, "unknown adapter 'ragbench'", one_line=False)


def test_missing_report_file(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    result = run_rf(
        ["import", sid, "-a", "rag-benchmarking", "-r", "missing.json"]
        + ["--project-dir", str(tmp_path)]
    )
    _assert_clean(result, 3, "does not exist", one_line=False)


def test_unknown_export_format(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    result = run_rf(["export", sid, "-f", "docx", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "unknown format 'docx'", one_line=False)


def test_unknown_dimension(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    result = run_rf(
        ["risk", "list", sid, "--dimension", "privacyy", "--project-dir", str(tmp_path)]
    )
    _assert_clean(result, 3, "not a risk dimension", one_line=False)


def test_residual_score_out_of_range(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    register = next((tmp_path / ".riskforge" / "systems").glob("*/register.yaml")).read_text()
    rid = re.search(r"- id: ([0-9a-f]{8})", register).group(1)
    result = run_rf(
        [
            "risk",
            "mitigate",
            sid,
            rid,
            "-m",
            "Block release above 0.10 parity gap",
            "-c",
            "preventive",
            "--owner",
            "X",
            "--residual-likelihood",
            "7",
            "--project-dir",
            str(tmp_path),
        ]
    )
    _assert_clean(result, 3, "--residual-likelihood", one_line=False)


def test_unknown_risk_id(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    result = run_rf(["risk", "accept", sid, "00000000", "-r", "x", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "No risk item matches")


def test_interactive_assess_without_a_terminal(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    result = run_rf(["assess", sid, "-a", "A", "-r", "B", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "needs a terminal")
    assert not list((tmp_path / ".riskforge" / "systems").glob("*/register.yaml"))


def test_answers_file_with_invalid_value(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    answers = tmp_path / "answers.yaml"
    answers.write_text("answers:\n  PR-001: { applies: maybe }\n")
    result = run_rf(
        ["assess", sid, "-a", "A", "-r", "B", "--answers", str(answers)]
        + ["--project-dir", str(tmp_path)]
    )
    _assert_clean(result, 3, "invalid applies")


def test_answers_file_with_score_out_of_range(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    answers = tmp_path / "answers.yaml"
    answers.write_text("answers:\n  PR-001: { applies: yes, likelihood: 7, severity: 2 }\n")
    result = run_rf(
        ["assess", sid, "-a", "A", "-r", "B", "--answers", str(answers)]
        + ["--project-dir", str(tmp_path)]
    )
    _assert_clean(result, 3, "use a whole number from 1 to 5")


def test_verify_file_that_is_not_json(tmp_path: Path) -> None:
    markdown = tmp_path / "rmf.md"
    markdown.write_text("# not json\n")
    _assert_clean(run_rf(["verify", "--file", str(markdown)]), 3, "not a JSON")


def test_diff_with_a_file_that_is_not_an_rmf(tmp_path: Path) -> None:
    markdown = tmp_path / "rmf.md"
    markdown.write_text("# not json\n")
    _assert_clean(run_rf(["diff", "x", str(markdown), str(markdown)]), 3, "not a JSON RMF file")


def test_empty_acceptance_rationale(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    rid = _first_risk_id(tmp_path)
    result = run_rf(["risk", "accept", sid, rid, "-r", " ", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "rationale is required")


def test_system_id_with_a_path_separator(tmp_path: Path) -> None:
    _init(tmp_path)
    result = run_rf(["system", "show", "../x", "--project-dir", str(tmp_path)])
    _assert_clean(result, 3, "must not contain path separators")


# A corrupted or hand-edited project file is not a user mistake: it must never exit 3.


def test_corrupt_audit_log_is_not_a_usage_error(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    rid = _first_risk_id(tmp_path)
    audit = tmp_path / ".riskforge" / "audit.jsonl"
    lines = audit.read_text().splitlines()
    audit.write_text("\n".join(lines[:-1] + [lines[-1][: len(lines[-1]) // 2]]) + "\n")
    result = run_rf(["risk", "accept", sid, rid, "-r", "ok", "--project-dir", str(tmp_path)])
    assert result.returncode not in (0, 3), result.output


def test_corrupt_system_file_is_not_a_usage_error(tmp_path: Path) -> None:
    sid = _init(tmp_path)
    system_file = tmp_path / ".riskforge" / "systems" / sid / "system.yaml"
    text = system_file.read_text()
    assert "annex_iii_category: essential_services" in text
    system_file.write_text(text.replace("essential_services", "not_a_category"))
    result = run_rf(["validate", sid, "--project-dir", str(tmp_path)])
    assert result.returncode not in (0, 3), result.output


def _first_risk_id(project: Path) -> str:
    register = next((project / ".riskforge" / "systems").glob("*/register.yaml")).read_text()
    return re.search(r"- id: ([0-9a-f]{8})", register).group(1)


RAG_BENCHMARK_REPORT = REPO / "tests/fixtures/upstream/rag_benchmarking_benchmark_report.json"


def test_import_of_a_real_rag_benchmarking_report(tmp_path: Path) -> None:
    """Control for the NaN case below: the unmodified report imports (PRD-330)."""
    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    result = run_rf(
        ["import", sid, "-a", "rag-benchmarking", "-r", str(RAG_BENCHMARK_REPORT)]
        + ["--project-dir", str(tmp_path)]
    )
    assert result.returncode == 0, result.output
    assert "Imported 2 risk item(s)" in result.output, result.output
    register = next((tmp_path / ".riskforge" / "systems").glob("*/register.yaml")).read_text()
    assert register.count("source_ref: rag:riskforge-fixture-001") == 2, register


def test_import_refuses_a_nan_metric_and_leaves_the_register(tmp_path: Path) -> None:
    import json

    sid = _init(tmp_path)
    _assess(tmp_path, sid)
    register = next((tmp_path / ".riskforge" / "systems").glob("*/register.yaml"))
    audit_log = tmp_path / ".riskforge" / "audit.jsonl"
    before = register.read_bytes()
    audit_before = audit_log.read_bytes()
    assert audit_before
    report = json.loads(RAG_BENCHMARK_REPORT.read_text(encoding="utf-8"))
    report["metrics"]["faithfulness"] = float("nan")
    path = tmp_path / "nan-report.json"
    path.write_text(json.dumps(report))
    result = run_rf(
        ["import", sid, "-a", "rag-benchmarking", "-r", str(path)]
        + ["--project-dir", str(tmp_path)]
    )
    _assert_clean(result, 3, "faithfulness")
    assert register.read_bytes() == before
    assert audit_log.read_bytes() == audit_before
