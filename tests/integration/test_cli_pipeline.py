"""Integration tests — end-to-end CLI pipeline via subprocess.

These tests invoke the installed `riskforge` binary directly, which is the
most reliable way to test a CLI that uses Rich Console (module-level Console()
objects capture the real stdout at import time, bypassing CliRunner's patch).

The assess command requires interactive terminal prompts so it is not tested
here. AssessEngine is covered in unit/test_audit_chain.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rf_testkit import run_rf


def _run(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run riskforge <args> offline; the result carries ``.output``."""
    return run_rf(args, cwd=cwd)


def _init_project(tmp_dir: Path, name: str = "Pipeline Test System") -> str:
    """Run riskforge init and return the system_id."""
    result = _run(
        [
            "init",
            "--name",
            name,
            "--sys-version",
            "2.0",
            "--purpose",
            f"Integration test for {name}.",
            "--provider",
            "AI Exponent LLC",
            "--category",
            "employment",
            "--project-dir",
            str(tmp_dir),
        ]
    )
    assert result.returncode == 0, f"init failed:\nSTDOUT:{result.stdout}\nSTDERR:{result.stderr}"
    sid = next(
        (
            line.split(":", 1)[-1].strip()
            for line in result.output.splitlines()
            if "System ID:" in line
        ),
        None,
    )
    assert sid, f"Could not extract system ID from:\n{result.output}"
    return sid


def _seed_register(tmp_dir: Path, sid: str, one_dim: bool = False, classify: bool = True) -> None:
    """Seed a register directly via the engine (bypasses interactive assess)."""
    import asyncio

    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.register import RiskRegister
    from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
    from riskforge.storage.filesystem import FileStore

    async def _run_async():
        store = FileStore(tmp_dir)
        sys_obj = await store.read_system(sid)
        sys_obj.annex_iii_self_classification_documented = classify
        await store.write_system(sid, sys_obj)
        reg = RiskRegister(
            system=sys_obj,
            assessor_name="Test Assessor",
            assessor_role="QA Engineer",
            assessment_date=datetime.now(UTC),
            review_date=datetime.now(UTC) + timedelta(days=365),
            question_bank_version="1.0.0",
        )
        await store.write_register(sid, reg)
        actor = AuditActor(type="ci", identity="integration-test")
        audit = AuditEngine(store, actor)
        engine = RiskEngine(store, audit)
        dims = [RiskDimension.privacy] if one_dim else list(RiskDimension)
        for dim in dims:
            item = RiskItem(
                dimension=dim,
                title=f"Integration test risk — {dim.value}",
                description=f"Seeded by integration test for {dim.value}.",
                source="manual",
                likelihood=Likelihood.possible,
                severity=Severity.moderate,
                residual_likelihood=Likelihood.unlikely,
                residual_severity=Severity.minor,
            )
            await engine.add_risk(sid, item)

    asyncio.run(_run_async())


def test_version_shows_zero_telemetry() -> None:
    """riskforge --version must include the zero-telemetry trust signal."""
    result = _run(["--version"])
    assert result.returncode == 0, f"--version failed:\n{result.stderr}"
    assert "Zero telemetry" in result.output
    assert "Apache 2.0" in result.output


def test_init_creates_project_files() -> None:
    """riskforge init must create .riskforge/ and riskforge.yaml."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Init Test System")
        assert (d / "riskforge.yaml").exists(), "riskforge.yaml not created"
        assert (d / ".riskforge").is_dir(), ".riskforge/ directory not created"
        assert len(sid) > 10, f"Unexpected system ID: {sid}"


def test_full_pipeline_init_validate_export_verify() -> None:
    """Full pipeline: init → seed → validate → export json → verify."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)

        # 1. Init
        sid = _init_project(d)

        # 2. Seed register (replaces interactive assess in CI)
        _seed_register(d, sid)

        # 3. Validate
        validate_result = _run(
            [
                "validate",
                sid,
                "--project-dir",
                str(d),
            ]
        )
        assert validate_result.returncode in (
            0,
            1,
        ), f"validate exited {validate_result.returncode}:\n{validate_result.stdout}"

        # 4. Export JSON
        output_json = d / "test_rmf.json"
        export_result = _run(
            [
                "export",
                sid,
                "--format",
                "json",
                "--output",
                str(output_json),
                "--force",
                "--project-dir",
                str(d),
            ]
        )
        assert (
            export_result.returncode == 0
        ), f"export json failed:\n{export_result.stdout}\n{export_result.stderr}"
        assert output_json.exists(), "rmf.json not created"

        rmf = json.loads(output_json.read_text())
        assert "rmf_schema_version" in rmf
        assert "register" in rmf
        assert len(rmf["register"]["items"]) == 8
        assert rmf["sha256_hash"] != ""

        # 5. Verify audit chain
        verify_result = _run(
            [
                "verify",
                "--project-dir",
                str(d),
            ]
        )
        assert (
            verify_result.returncode == 0
        ), f"verify failed (chain corrupt):\n{verify_result.stdout}"
        assert "verified" in (verify_result.stdout + verify_result.stderr).lower()


def test_export_markdown_contains_risk_items() -> None:
    """Markdown export must contain actual risk item text."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Markdown Test System")
        _seed_register(d, sid, one_dim=True)

        out = d / "test.md"
        result = _run(
            [
                "export",
                sid,
                "--format",
                "markdown",
                "--output",
                str(out),
                "--force",
                "--project-dir",
                str(d),
            ]
        )
        assert result.returncode == 0, f"markdown export failed:\n{result.stderr}"
        assert out.exists()
        content = out.read_text()
        assert "Risk Management" in content
        assert "Integration test risk" in content


def test_risk_accept_by_prefix_and_clean_error() -> None:
    """`risk accept` resolves the 8-char id from `risk list`; unknown ids exit 3 cleanly."""
    import asyncio

    from riskforge.storage.filesystem import FileStore

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Accept Test System")
        _seed_register(d, sid, one_dim=True)

        reg = asyncio.run(FileStore(d).read_register(sid))
        prefix = str(reg.items[0].id)[:8]

        ok = _run(
            ["risk", "accept", sid, prefix, "-r", "Accepted after review.", "--project-dir", str(d)]
        )
        assert ok.returncode == 0, f"prefix accept failed:\n{ok.output}"
        assert "accepted" in ok.output.lower()

        bad = _run(["risk", "accept", sid, "00000000", "-r", "x", "--project-dir", str(d)])
        assert bad.returncode == 3, f"expected clean exit 3, got {bad.returncode}:\n{bad.output}"
        assert "Traceback" not in bad.output, f"unhandled crash:\n{bad.output}"
        assert "No risk item matches" in bad.output


def test_system_classify_clears_g2() -> None:
    """`system classify --confirm` records Article 6(2) so validation gate G2 passes.

    Before this command existed there was no CLI path to set the flag, so validation
    could never pass without hand-editing state files or using --force.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Classify Test System")
        _seed_register(d, sid, classify=False)

        before = _run(["validate", sid, "--project-dir", str(d)])
        assert (
            before.returncode == 1
        ), f"G2 should block validation before classify:\n{before.output}"

        cls = _run(["system", "classify", sid, "--confirm", "--project-dir", str(d)])
        assert cls.returncode == 0, f"classify failed:\n{cls.output}"
        assert "recorded" in cls.output.lower()

        show = _run(["system", "show", sid, "--project-dir", str(d)])
        assert '"annex_iii_self_classification_documented": true' in show.output

        after = _run(["validate", sid, "--project-dir", str(d)])
        assert after.returncode == 0, f"validation should pass after classify:\n{after.output}"

        chain = _run(["verify", "--project-dir", str(d)])
        assert chain.returncode == 0, f"classify must not break the audit chain:\n{chain.output}"


def test_verify_file_detects_tampered_rmf() -> None:
    """`verify --file` validates a standalone RMF's digest: exit 0 clean, exit 2 tampered."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Verify File System")
        _seed_register(d, sid)
        out = d / "rmf.json"
        exp = _run(
            ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)]
        )
        assert exp.returncode == 0, f"export failed:\n{exp.output}"

        clean = _run(["verify", "--file", str(out)])
        assert clean.returncode == 0, f"clean RMF should verify (0):\n{clean.output}"

        data = json.loads(out.read_text())
        data["register"]["items"][0]["title"] = "TAMPERED BY ATTACKER"
        out.write_text(json.dumps(data, indent=2))

        tampered = _run(["verify", "--file", str(out)])
        assert (
            tampered.returncode == 2
        ), f"tampered RMF must exit 2, got {tampered.returncode}:\n{tampered.output}"


def test_assess_noninteractive_from_answers_file() -> None:
    """`assess --answers` builds the register non-interactively from a YAML file."""
    import asyncio

    import riskforge._data as _data_pkg
    from riskforge.engine.assess import AssessEngine
    from riskforge.models.risk import RiskDimension
    from riskforge.storage.filesystem import FileStore

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Answers Test System")

        engine = AssessEngine(Path(_data_pkg.__file__).parent)
        priv_q = engine.load_questions(RiskDimension.privacy)[0]["id"]
        disc_q = engine.load_questions(RiskDimension.discrimination)[0]["id"]

        answers = d / "answers.yaml"
        answers.write_text(
            "add_patterns: true\n"
            "answers:\n"
            f"  {priv_q}: {{ applies: yes, likelihood: 4, severity: 5 }}\n"
            f"  {disc_q}: {{ applies: unknown }}\n"
        )

        res = _run(
            [
                "assess",
                sid,
                "-a",
                "Alice",
                "-r",
                "Lead",
                "--answers",
                str(answers),
                "--project-dir",
                str(d),
            ]
        )
        assert res.returncode == 0, f"non-interactive assess failed:\n{res.output}"

        reg = asyncio.run(FileStore(d).read_register(sid))
        assert any(
            i.source == "question_bank" and i.risk_score == 20 for i in reg.items
        ), f"scored item (4x5=20) missing:\n{[(i.source, i.risk_score) for i in reg.items]}"
        assert any(i.knowledge_gap for i in reg.items), "knowledge-gap item missing"


def test_assess_noninteractive_missing_file_exits_3() -> None:
    """A missing answers file is a clean exit 3 (input error), not a traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Answers Missing System")
        res = _run(
            [
                "assess",
                sid,
                "-a",
                "A",
                "-r",
                "B",
                "--answers",
                str(d / "nope.yaml"),
                "--project-dir",
                str(d),
            ]
        )
        assert res.returncode == 3, f"expected exit 3, got {res.returncode}:\n{res.output}"
        assert "Traceback" not in res.output


def test_export_populates_test_requirements_and_cross_references() -> None:
    """Exported RMF carries derived Article 9 test requirements and cross-references."""
    import riskforge._data as _data_pkg
    from riskforge.engine.assess import AssessEngine
    from riskforge.models.risk import RiskDimension

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "RMF Fields System")
        priv_q = AssessEngine(Path(_data_pkg.__file__).parent).load_questions(
            RiskDimension.privacy
        )[0]["id"]
        (d / "answers.yaml").write_text(
            f"add_patterns: false\nanswers:\n  {priv_q}: {{ applies: yes, likelihood: 4, severity: 5 }}\n"
        )
        assert (
            _run(
                [
                    "assess",
                    sid,
                    "-a",
                    "A",
                    "-r",
                    "B",
                    "--answers",
                    str(d / "answers.yaml"),
                    "-d",
                    str(d),
                ]
            ).returncode
            == 0
        )
        out = d / "rmf.json"
        exp = _run(
            ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)]
        )
        assert exp.returncode == 0, f"export failed:\n{exp.output}"
        rmf = json.loads(out.read_text())
        assert len(rmf["test_requirements"]) >= 1, "test_requirements should be derived at export"
        assert len(rmf["cross_references"]) >= 1, "cross_references should be derived at export"


def test_export_records_audit_entry_hash_in_file() -> None:
    """The exported RMF carries the hash of its rmf.exported audit entry; verify --file still holds."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "AEH System")
        _seed_register(d, sid)
        out = d / "rmf.json"
        exp = _run(
            ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)]
        )
        assert exp.returncode == 0, f"export failed:\n{exp.output}"

        rmf = json.loads(out.read_text())
        assert rmf["audit_entry_hash"], "audit_entry_hash must be populated in the exported file"

        entries = [
            json.loads(line) for line in (d / ".riskforge" / "audit.jsonl").read_text().splitlines()
        ]
        exported = [e for e in entries if e["event"] == "rmf.exported"]
        assert exported and exported[-1]["entry_hash"] == rmf["audit_entry_hash"]

        assert _run(["verify", "--file", str(out), "--project-dir", str(d)]).returncode == 0


def test_risk_mitigate_adds_mitigation_and_rescores() -> None:
    """`risk mitigate` adds a mitigation via the CLI, re-scores residual, audits, and exports."""
    import asyncio

    from riskforge.storage.filesystem import FileStore

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Mitigate System")
        _seed_register(d, sid, one_dim=True)
        rid = str(asyncio.run(FileStore(d).read_register(sid)).items[0].id)[:8]

        res = _run(
            [
                "risk",
                "mitigate",
                sid,
                rid,
                "-m",
                "Remove postcode feature; add demographic parity monitoring.",
                "-c",
                "preventive",
                "--owner",
                "ML Platform",
                "--status",
                "implemented",
                "--residual-likelihood",
                "1",
                "--residual-severity",
                "1",
                "--project-dir",
                str(d),
            ]
        )
        assert res.returncode == 0, f"mitigate failed:\n{res.output}"

        reg = asyncio.run(FileStore(d).read_register(sid))
        assert len(reg.items[0].mitigations) == 1
        assert reg.items[0].residual_risk_score == 1
        assert _run(["verify", "--project-dir", str(d)]).returncode == 0

        out = d / "rmf.json"
        assert (
            _run(
                ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)]
            ).returncode
            == 0
        )
        rmf = json.loads(out.read_text())
        assert any(i["mitigations"] for i in rmf["register"]["items"])


def test_risk_mitigate_flags_vague() -> None:
    """A vague mitigation description is flagged to the user."""
    import asyncio

    from riskforge.storage.filesystem import FileStore

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Vague System")
        _seed_register(d, sid, one_dim=True)
        rid = str(asyncio.run(FileStore(d).read_register(sid)).items[0].id)[:8]
        res = _run(
            [
                "risk",
                "mitigate",
                sid,
                rid,
                "-m",
                "we'll monitor it",
                "-c",
                "detective",
                "--owner",
                "X",
                "--project-dir",
                str(d),
            ]
        )
        assert res.returncode == 0, res.output
        assert "vague" in res.output.lower()


def test_rmf_export_structure_is_locked() -> None:
    """Lock the exported RMF top-level + mitigation key sets (guards model/schema drift, e.g. B1)."""
    import asyncio

    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.risk import Mitigation
    from riskforge.storage.filesystem import FileStore

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "Structure System")
        _seed_register(d, sid, one_dim=True)

        async def _add_mit():
            store = FileStore(d)
            audit = AuditEngine(store, AuditActor(type="ci", identity="t"))
            eng = RiskEngine(store, audit)
            reg = await store.read_register(sid)
            await eng.add_mitigation(
                sid,
                str(reg.items[0].id),
                Mitigation(
                    description="Specific documented control.",
                    control_type="preventive",
                    owner="ML",
                    status="implemented",
                    article_ref="Art.9(2)(d)",
                    nist_rmf_ref="MANAGE 1.3",
                ),
            )

        asyncio.run(_add_mit())

        out = d / "rmf.json"
        assert (
            _run(
                ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)]
            ).returncode
            == 0
        )
        rmf = json.loads(out.read_text())

        assert set(rmf) == {
            "id",
            "rmf_schema_version",
            "register",
            "test_requirements",
            "cross_references",
            "generated_at",
            "sha256_hash",
            "signed_by",
            "audit_entry_hash",
            "disclosure",
        }
        mit = next(m for i in rmf["register"]["items"] for m in i["mitigations"])
        assert set(mit) == {
            "id",
            "description",
            "control_type",
            "owner",
            "status",
            "evidence_refs",
            "is_vague",
            "article_ref",
            "nist_rmf_ref",
        }
        assert rmf["disclosure"]

        md = d / "rmf.md"
        assert (
            _run(
                ["export", sid, "-f", "markdown", "-o", str(md), "--force", "--project-dir", str(d)]
            ).returncode
            == 0
        )
        md_text = md.read_text()
        assert "# Risk Management File" in md_text
        assert "## Risk Items" in md_text


def test_risk_list_shows_seeded_items() -> None:
    """riskforge risk list must return seeded items."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        sid = _init_project(d, "List Test System")
        _seed_register(d, sid, one_dim=True)

        result = _run(["risk", "list", sid, "--project-dir", str(d)])
        assert result.returncode == 0, f"risk list failed:\n{result.stderr}"
        assert "privacy" in (result.stdout + result.stderr).lower()
