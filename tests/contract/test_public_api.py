"""riskforge.api is the supported surface for applications built on RiskForge."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

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
    "ExportResult",
    "FieldChange",
    "GateResult",
    "GateStatus",
    "IntegrityError",
    "IntegrityReport",
    "ItemChange",
    "KeyFileError",
    "RegisterDiff",
    "RiskNotFoundError",
    "RmfCheck",
    "SchemaViolationError",
    "UnsupportedRmfVersionError",
    "UpsertOutcome",
    "ValidationGateError",
    # functions
    "build_cross_references",
    "build_receipt",
    "canonical_json",
    "check_integrity",
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
    "receipt_from_document",
    "require_intact",
    "rmf_document",
    "rmf_signing_message",
    "signoff_signing_message",
    "verify_signature",
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


async def test_an_embedding_application_runs_the_whole_flow(tmp_path: Path) -> None:
    key = tmp_path / "signing.pem"
    private_pem, _public_pem = rf.generate_key_pair_pem()
    key.write_bytes(private_pem)
    key.chmod(0o600)
    signer = rf.Ed25519Signer.from_file(key)

    store = rf.FileStore(tmp_path / "project")
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
                title=f"{dimension.value} risk from the workshop",
                description="Recorded during the assessment workshop.",
                likelihood=rf.Likelihood(3),
                severity=rf.Severity(3),
                residual_likelihood=rf.Likelihood(2),
                residual_severity=rf.Severity(3),
            ),
        )
    register = await store.read_register(system_id)
    await risks.set_test_requirements(system_id, rf.TestDerivationEngine().derive(register.items))
    gates = rf.ValidateEngine().run(await store.read_register(system_id))
    assert not rf.ValidateEngine().has_failures(gates), [
        g for g in gates if g.status == rf.GateStatus.FAIL
    ]

    registry = rf.PluginRegistry()
    registry.load_all()
    result = await rf.ExportEngine(registry, audit, store).export(
        system_id, "json", tmp_path / "rmf.json", signer=signer
    )
    document = json.loads(result.path.read_text(encoding="utf-8"))
    check = rf.check_rmf_document(document, trusted_keys=[signer.public_key_b64])
    assert check.ok, check.findings
    assert check.trusted_key_checked
    assert document["sha256_hash"] == result.content_digest == rf.content_digest(document)
    assert (await rf.check_integrity(store)).ok

    # A changed file fails the same check the CLI's `verify --file` runs.
    document["register"]["items"][0]["title"] = "Edited after export"
    assert not rf.check_rmf_document(document, trusted_keys=[signer.public_key_b64]).ok


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
    result = subprocess.run(
        [sys.executable, "-c", _doc_example()],
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
        "Signed RMF verified: True",
        "Audit chain intact: True",
    ]
