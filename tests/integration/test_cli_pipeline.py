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
from pathlib import Path

import pytest
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
    """Seed a register through the engines (bypasses interactive assess)."""
    import asyncio

    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.risk import RiskEngine
    from riskforge.engine.system import SystemEngine
    from riskforge.models.audit import AuditActor
    from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity
    from riskforge.storage.filesystem import FileStore

    async def _run_async():
        store = FileStore(tmp_dir)
        actor = AuditActor(type="ci", identity="integration-test")
        audit = AuditEngine(store, actor)
        if classify:
            await SystemEngine(store, audit).classify(sid, None)
        engine = RiskEngine(store, audit)
        await engine.create_register(sid, "Test Assessor", "QA Engineer")
        dims = [RiskDimension.privacy] if one_dim else list(RiskDimension)
        for dim in dims:
            item = RiskItem(
                dimension=dim,
                title=f"Integration test risk: {dim.value}",
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
            ["risk", "accept", sid, prefix, "-r", "Accepted after review.", "--by", "Jane Doe"]
            + ["--project-dir", str(d)]
        )
        assert ok.returncode == 0, f"prefix accept failed:\n{ok.output}"
        assert "accepted" in ok.output.lower()

        bad = _run(
            [
                "risk",
                "accept",
                sid,
                "00000000",
                "-r",
                "x",
                "--by",
                "Jane Doe",
                "--project-dir",
                str(d),
            ]
        )
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


def _export_json(d: Path, name: str) -> Path:
    sid = _init_project(d, name)
    _seed_register(d, sid)
    out = d / "rmf.json"
    exp = _run(["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)])
    assert exp.returncode == 0, f"export failed:\n{exp.output}"
    return out


def test_json_export_is_rmf_1_1_0_and_validates(tmp_path: Path) -> None:
    """New exports declare 1.1.0, validate against its schema and carry the content digest."""
    import jsonschema
    from riskforge.integrity.rmf import content_digest, load_schema

    rmf = json.loads(_export_json(tmp_path, "RMF 1.1 System").read_text())
    assert rmf["rmf_schema_version"] == "1.1.0"
    jsonschema.validate(rmf, load_schema("1.1.0"))
    assert "signed_by" not in rmf
    assert "audit_entry_hash" not in rmf
    assert (rmf["signoffs"], rmf["signatures"], rmf["public_keys"]) == ([], [], [])
    assert rmf["sha256_hash"] == content_digest(rmf)

    entries = [
        json.loads(line)
        for line in (tmp_path / ".riskforge" / "audit.jsonl").read_text().splitlines()
    ]
    exported = [e for e in entries if e["event"] == "rmf.exported"]
    assert exported[-1]["payload"]["sha256"] == rmf["sha256_hash"]


def test_verify_file_ignores_id_and_generation_time_of_a_1_1_0_file(tmp_path: Path) -> None:
    """id and generated_at sit outside the 1.1.0 content digest; the register does not."""
    out = _export_json(tmp_path, "Digest Scope System")
    data = json.loads(out.read_text())
    data["id"] = "00000000-0000-4000-8000-000000000000"
    data["generated_at"] = "2030-01-01T00:00:00Z"
    out.write_text(json.dumps(data, indent=2))
    assert _run(["verify", "--file", str(out)]).returncode == 0

    data["register"]["assessor_name"] = "Someone else"
    out.write_text(json.dumps(data, indent=2))
    assert _run(["verify", "--file", str(out)]).returncode == 2


def test_verify_file_refuses_a_retired_field_added_to_a_1_1_0_file(tmp_path: Path) -> None:
    """Under 1.1.0 audit_entry_hash is content, so adding one changes the digest."""
    out = _export_json(tmp_path, "Retired Field System")
    data = json.loads(out.read_text())
    data["audit_entry_hash"] = "0" * 64
    out.write_text(json.dumps(data, indent=2))
    assert _run(["verify", "--file", str(out)]).returncode == 2


def test_verify_file_refuses_a_duplicate_key(tmp_path: Path) -> None:
    """The file is read strictly: a duplicate key could show one value and hash another."""
    out = _export_json(tmp_path, "Duplicate Key System")
    text = out.read_text()
    out.write_text(text.replace('"disclosure":', '"disclosure": "x",\n  "disclosure":', 1))
    result = _run(["verify", "--file", str(out)])
    assert result.returncode == 2, result.output
    assert "duplicate key" in result.output


def test_verify_file_refuses_an_unknown_schema_version(tmp_path: Path) -> None:
    out = _export_json(tmp_path, "Unknown Version System")
    data = json.loads(out.read_text())
    data["rmf_schema_version"] = "9.9.9"
    out.write_text(json.dumps(data, indent=2))
    result = _run(["verify", "--file", str(out)])
    assert result.returncode == 3, result.output
    assert "9.9.9" in result.output


def _rewrite(out: Path, data: dict) -> None:
    """Write ``data`` back with a recomputed content digest, as a forger would."""
    from riskforge.integrity.rmf import content_digest

    data["sha256_hash"] = content_digest(data)
    out.write_text(json.dumps(data, indent=2))


_FAKE_SIGNATURE = {
    "key_id": "ed25519:0123456789abcdef",
    "algorithm": "ed25519",
    "signed_at": "2026-10-01T00:00:00Z",
    "signature": "A" * 86 + "==",
}


def test_verify_file_validates_the_schema_before_it_reports_a_match(tmp_path: Path) -> None:
    """ADR-04 section 6 step 1: a recomputed digest does not make a malformed 1.1.0 file valid."""
    out = _export_json(tmp_path, "Schema Check System")
    data = json.loads(out.read_text())
    data["signed_by"] = "someone@example.com"
    data["audit_entry_hash"] = "0" * 64
    data["signatures"] = [{**_FAKE_SIGNATURE, "signature": "not base64"}]
    _rewrite(out, data)
    result = _run(["verify", "--file", str(out)])
    assert result.returncode == 2, result.output
    assert "verified" not in result.output
    assert "schema 1.1.0" in result.output
    assert "signed_by" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("version", [["1.1.0"], {"v": "1.1.0"}, 110])
def test_verify_file_refuses_a_schema_version_that_is_not_a_string(
    tmp_path: Path, version: object
) -> None:
    out = _export_json(tmp_path, "Version Type System")
    data = json.loads(out.read_text())
    data["rmf_schema_version"] = version
    out.write_text(json.dumps(data, indent=2))
    result = _run(["verify", "--file", str(out)])
    assert result.returncode == 3, result.output
    assert "Traceback" not in result.output
    assert "rmf_schema_version" in result.output


def test_verify_file_says_provenance_blocks_were_not_checked(tmp_path: Path) -> None:
    """Until signatures are verified, a well-formed but bogus one must not pass silently."""
    out = _export_json(tmp_path, "Not Checked System")
    data = json.loads(out.read_text())
    data["signatures"] = [_FAKE_SIGNATURE]
    _rewrite(out, data)
    result = _run(["verify", "--file", str(out)])
    assert result.returncode == 0, result.output
    # Every export also carries a chain proof and a receipt (ADR-04 section 7).
    assert "Not checked: signatures, chain_proof, receipt." in result.output


def test_verify_file_refuses_an_integer_too_long_for_python(tmp_path: Path) -> None:
    out = _export_json(tmp_path, "Long Integer System")
    text = out.read_text()
    out.write_text(text.replace('"disclosure":', '"n": ' + "9" * 5000 + ',\n  "disclosure":', 1))
    result = _run(["verify", "--file", str(out)])
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output
    assert "too long" in result.output


def test_verify_file_prints_the_stored_digest_escaped(tmp_path: Path) -> None:
    """The stored sha256_hash comes from the file: no markup or control character reaches the terminal."""
    out = _export_json(tmp_path, "Escaped Digest System")
    data = json.loads(out.read_text())
    data["sha256_hash"] = "\x1b[31m[bold]x[/bold]"
    out.write_text(json.dumps(data, indent=2))
    result = _run(["verify", "--file", str(out)])
    assert result.returncode == 2, result.output
    assert "\x1b" not in result.output
    assert "[bold]x[/bold]" in result.output


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
    """`tests generate` saves requirements once; export carries exactly the saved ones."""
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
        empty = _run(
            ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)]
        )
        assert empty.returncode == 0, f"export failed:\n{empty.output}"
        assert json.loads(out.read_text())["test_requirements"] == []

        log = d / ".riskforge" / "audit.jsonl"
        generated = _run(["tests", "generate", sid, "--project-dir", str(d)])
        assert generated.returncode == 0, generated.output
        assert "Saved" in generated.output
        entries = [json.loads(line) for line in log.read_text().splitlines()]
        assert entries[-1]["event"] == "tests.generated"
        assert entries[-1]["payload"]["count"] >= 1

        log_before = log.read_bytes()
        again = _run(["tests", "generate", sid, "--project-dir", str(d)])
        assert again.returncode == 0, again.output
        assert "Saved" not in again.output
        assert "Unchanged" in again.output
        assert log.read_bytes() == log_before

        exp = _run(
            ["export", sid, "-f", "json", "-o", str(out), "--force", "--project-dir", str(d)]
        )
        assert exp.returncode == 0, f"export failed:\n{exp.output}"
        rmf = json.loads(out.read_text())
        assert len(rmf["test_requirements"]) >= 1, "saved test_requirements should be exported"
        assert rmf["test_requirements"] == rmf["register"]["test_requirements"]
        assert len(rmf["cross_references"]) >= 1, "cross_references should be derived at export"

        second = d / "rmf-again.json"
        exp2 = _run(
            ["export", sid, "-f", "json", "-o", str(second), "--force", "--project-dir", str(d)]
        )
        assert exp2.returncode == 0, exp2.output
        rmf2 = json.loads(second.read_text())
        assert rmf2["id"] != rmf["id"]
        assert rmf2["sha256_hash"] == rmf["sha256_hash"]


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
                "--by",
                "Jane Doe",
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
                "--by",
                "Jane Doe",
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
            "disclosure",
            "signoffs",
            "signatures",
            "public_keys",
            "chain_proof",
            "receipt",
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
