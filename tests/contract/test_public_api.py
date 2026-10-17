"""riskforge.api is the supported surface for applications built on RiskForge."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import riskforge.api as rf
from rf_testkit import offline_env

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "library-api.md"

PUBLIC = {
    # engines
    "AssessEngine",
    "AuditEngine",
    "ExportEngine",
    "RiskEngine",
    "SystemEngine",
    "TestDerivationEngine",
    "ValidateEngine",
    # results and errors
    "AmbiguousRiskIdError",
    "ChangeInProgressError",
    "ExportError",
    "ExportResult",
    "FieldChange",
    "GateResult",
    "GateStatus",
    "IntegrityError",
    "IntegrityReport",
    "InvalidReceiptError",
    "ItemChange",
    "KeyFileError",
    "NumberTooLongError",
    "ReceiptFileError",
    "RegisterDiff",
    "RiskNotFoundError",
    "RmfCheck",
    "RmfFileError",
    "SchemaViolationError",
    "StrictJsonError",
    "UnsupportedRmfVersionError",
    "UpsertOutcome",
    "UpsertResult",
    "ValidationGateError",
    # functions
    "build_cross_references",
    "build_receipt",
    "canonical_json",
    "check_integrity",
    "check_integrity_settled",
    "check_receipt",
    "check_rmf_document",
    "content_digest",
    "diff_registers",
    "document_fingerprint",
    "generate_key_pair_pem",
    "key_id_for",
    "keyword_matches",
    "load_public_key_b64",
    "origin_key",
    "read_receipt_file",
    "read_rmf_file",
    "reads_checked_against",
    "receipt_from_document",
    "require_intact",
    "rmf_document",
    "rmf_signing_message",
    "signoff_signing_message",
    "verify_signature",
    "write_key_pair",
    # signing
    "Ed25519Signer",
    # models
    "AISystem",
    "AnnexIIICategory",
    "AuditActor",
    "AuditEntry",
    "ChainProof",
    "CrossReference",
    "Likelihood",
    "Mitigation",
    "PublicKeyRecord",
    "Receipt",
    "RiskDimension",
    "RiskItem",
    "RiskManagementFile",
    "RiskRegister",
    "RmfSignature",
    "Severity",
    "SignOff",
    "TestRequirement",
    # storage and plugins
    "AuditLogCorruptError",
    "FileStore",
    "PendingChangeError",
    "PluginRegistry",
    "ProjectExistsError",
    "ProjectNotFoundError",
    "RegisterNotFoundError",
    "StorageBackend",
    "SystemNotFoundError",
}


def test_the_public_surface_is_exactly_the_locked_list() -> None:
    assert set(rf.__all__) == PUBLIC
    assert len(rf.__all__) == len(PUBLIC)
    missing = [name for name in rf.__all__ if not hasattr(rf, name)]
    assert missing == []


def test_every_public_name_is_documented() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert [name for name in sorted(rf.__all__) if f"`{name}`" not in doc] == []


def test_importing_the_api_loads_neither_the_cli_nor_weasyprint() -> None:
    code = (
        "import sys, riskforge.api\n"
        "print(sorted(m for m in ('typer', 'weasyprint', 'riskforge.cli') if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env=offline_env(),
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_assess_engine_defaults_to_the_bundled_question_bank() -> None:
    engine = rf.AssessEngine()
    assert len(engine.load_questions(rf.RiskDimension.privacy)) > 0
    assert len(engine.load_patterns()) > 0


def _public_key_file(key: Path) -> Path:
    return key.with_name(key.name + ".pub")


async def _signed_export(directory: Path, key: Path, title: str = "workshop") -> Path:
    """A project in ``directory`` with one risk per dimension, exported signed by ``key``."""
    signer = rf.Ed25519Signer.from_file(key)
    store = rf.FileStore(directory / "project")
    await store.init_project("embedded", {"created_by": "library api test"})
    audit = rf.AuditEngine(store, rf.AuditActor(type="api", identity="consultant@example.com"))
    system = rf.AISystem(
        name="Loan Scoring Model",
        version="2.1",
        purpose="Automated credit scoring for retail loan applications.",
        provider_name="Acme Financial Services",
    )
    system_id = str(system.id)
    systems = rf.SystemEngine(store, audit)
    await systems.create(system)
    await systems.classify(system_id, rf.AnnexIIICategory.essential_services)
    risks = rf.RiskEngine(store, audit)
    await risks.create_register(system_id, "Alice Chen", "AI Governance Lead")
    for dimension in rf.RiskDimension:
        await risks.add_risk(
            system_id,
            rf.RiskItem(
                dimension=dimension,
                title=f"{dimension.value} risk from the {title}",
                description="Recorded during the assessment workshop.",
                likelihood=rf.Likelihood(3),
                severity=rf.Severity(3),
                residual_likelihood=rf.Likelihood(2),
                residual_severity=rf.Severity(3),
            ),
        )
    register = await audit.read_register(system_id)
    await risks.set_test_requirements(system_id, rf.TestDerivationEngine().derive(register.items))
    gates = rf.ValidateEngine().run(await audit.read_register(system_id))
    assert not rf.ValidateEngine().has_failures(gates), [
        g for g in gates if g.status == rf.GateStatus.FAIL
    ]

    registry = rf.PluginRegistry()
    registry.load_all()
    result = await rf.ExportEngine(registry, audit, store).export(
        system_id, "json", directory / "rmf.json", signer=signer
    )
    assert result.path == directory / "rmf.json"
    return result.path


async def test_an_embedding_application_runs_the_whole_flow(tmp_path: Path) -> None:
    key = tmp_path / "signing.pem"
    public_b64 = rf.write_key_pair(key)
    trusted = [rf.load_public_key_b64(_public_key_file(key))]
    assert trusted == [public_b64]
    path = await _signed_export(tmp_path, key)

    # What `riskforge verify --file rmf.json --trusted-key signing.pem.pub` runs.
    document = rf.read_rmf_file(path)
    check = rf.check_rmf_document(document, trusted_keys=trusted)
    assert check.ok, check.findings
    assert check.trusted_key_checked
    assert check.verified
    assert document["sha256_hash"] == rf.content_digest(document)
    store = rf.FileStore(tmp_path / "project", read_only=True)
    report = await rf.check_integrity_settled(store)
    assert report.ok, report.errors
    assert report.strict().ok
    assert (await rf.check_integrity(store)).ok
    assert rf.read_receipt_file(path) == rf.receipt_from_document(document)

    # A changed file fails the same check.
    document["register"]["items"][0]["title"] = "Edited after export"
    edited = rf.check_rmf_document(document, trusted_keys=trusted)
    assert not edited.ok
    assert not edited.verified


async def test_ok_without_a_trusted_key_means_internally_consistent_only(tmp_path: Path) -> None:
    owner = tmp_path / "owner" / "signing.pem"
    owner.parent.mkdir()
    rf.write_key_pair(owner)
    genuine = await _signed_export(owner.parent, owner)
    # Anyone can build a whole file with their own key: chain proof, receipt, signature.
    forger = tmp_path / "forger" / "signing.pem"
    forger.parent.mkdir()
    rf.write_key_pair(forger)
    forged = await _signed_export(forger.parent, forger, title="forger's desk")
    trusted = [rf.load_public_key_b64(_public_key_file(owner))]

    self_signed = rf.check_rmf_document(rf.read_rmf_file(forged))
    assert self_signed.ok, self_signed.findings
    assert not self_signed.trusted_key_checked
    assert not self_signed.verified
    assert "anyone can rebuild" in self_signed.notes[-1]

    against_owner = rf.check_rmf_document(rf.read_rmf_file(forged), trusted_keys=trusted)
    assert not against_owner.ok
    assert not against_owner.verified

    unchecked = rf.check_rmf_document(rf.read_rmf_file(genuine))
    assert unchecked.ok
    assert not unchecked.verified
    assert rf.check_rmf_document(rf.read_rmf_file(genuine), trusted_keys=trusted).verified


async def test_the_strict_readers_refuse_a_duplicate_key(tmp_path: Path) -> None:
    key = tmp_path / "signing.pem"
    rf.write_key_pair(key)
    path = await _signed_export(tmp_path, key)
    trusted = [rf.load_public_key_b64(_public_key_file(key))]
    text = path.read_text(encoding="utf-8")
    assert text.startswith("{")
    # A second sha256_hash before the real one: json.loads keeps the last, so the edit
    # passes a check that skips the strict reader.
    duplicated = tmp_path / "duplicated.json"
    duplicated.write_text('{"sha256_hash": "' + "0" * 64 + '",' + text[1:], encoding="utf-8")
    lenient = json.loads(duplicated.read_text(encoding="utf-8"))
    assert rf.check_rmf_document(lenient, trusted_keys=trusted).verified

    with pytest.raises(rf.StrictJsonError, match="duplicate"):
        rf.read_rmf_file(duplicated)
    with pytest.raises(rf.InvalidReceiptError):
        rf.read_receipt_file(duplicated)
    not_json = tmp_path / "not.json"
    not_json.write_text("[]", encoding="utf-8")
    with pytest.raises(rf.RmfFileError):
        rf.read_rmf_file(not_json)
    with pytest.raises(rf.ReceiptFileError):
        rf.read_receipt_file(not_json)
    too_long = tmp_path / "too-long.json"
    too_long.write_text('{"n": ' + "9" * 5000 + "}", encoding="utf-8")
    with pytest.raises(rf.NumberTooLongError):
        rf.read_rmf_file(too_long)


async def test_reads_after_a_settled_check_are_compared_with_it(tmp_path: Path) -> None:
    key = tmp_path / "signing.pem"
    rf.write_key_pair(key)
    await _signed_export(tmp_path, key)
    store = rf.FileStore(tmp_path / "project", read_only=True)
    audit = rf.AuditEngine(store, rf.AuditActor(type="api", identity="reader"))
    report = await rf.check_integrity_settled(store)
    assert report.ok, report.errors
    (register_file,) = (tmp_path / "project" / ".riskforge").rglob("register.yaml")
    system_id = register_file.parent.name
    with rf.reads_checked_against(store, report):
        assert (await audit.read_register(system_id)).items
        # Changed outside RiskForge after the check, as a tamper test.
        text = register_file.read_text(encoding="utf-8")
        register_file.write_text(text.replace("from the workshop", "edited"), encoding="utf-8")
        with pytest.raises(rf.IntegrityError):
            await audit.read_register(system_id)


def test_the_error_and_result_types_are_the_engine_ones() -> None:
    assert issubclass(rf.ValidationGateError, rf.ExportError)
    assert issubclass(rf.SchemaViolationError, rf.ExportError)
    assert issubclass(rf.ChangeInProgressError, RuntimeError)
    assert rf.UpsertResult._fields == ("outcome", "item", "previous", "matches")


def _doc_example() -> str:
    doc = DOC.read_text(encoding="utf-8")
    example = doc.split("## Example", 1)[1]
    match = re.search(r"```python\n(.*?)```", example, re.DOTALL)
    assert match, "docs/library-api.md has no python block under ## Example"
    return match.group(1)


def test_the_documented_example_runs(tmp_path: Path) -> None:
    # pytest-cov hands no config file to a child started outside the repo, so the child
    # would record statement data the suite's branch data cannot be combined with. The
    # in-process flow test above covers the same code.
    env = {k: v for k, v in offline_env().items() if not k.startswith("COV_CORE_")}
    loaded = (
        "import sys\n"
        "print(sorted(m for m in ('typer', 'weasyprint', 'riskforge.cli') if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", _doc_example() + loaded],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=tmp_path,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "Gates passed: True",
        "RMF verified with the trusted key: True",
        "Audit chain intact: True",
        "[]",
    ]
