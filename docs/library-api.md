# RiskForge library API

RiskForge is a command-line tool, and the same engine is a Python library. Applications
that build on it, such as a review server or a CI integration, import from one module:

```python
import riskforge.api as rf
```

Every name listed on this page is supported. From 2.0.0, a release that removes one of
them or changes its behaviour incompatibly is a new major version. Anything you import
from another module of the package is internal and may change in any release.

Importing `riskforge.api` loads neither the command line nor WeasyPrint. PDF export
loads WeasyPrint only when you export a PDF.

## Storage

- `StorageBackend`: the abstract storage interface. Implement it to keep RiskForge data
  somewhere other than files. Every change goes through `unit_of_work()`. Inside it, a
  register or system write and the audit entry that records it become visible together.
- `FileStore`: the file-based backend the CLI uses (`.riskforge/` plus `riskforge.yaml`).
  `FileStore(path, read_only=True)` checks a project without writing to it.
- Errors: `ProjectNotFoundError`, `ProjectExistsError`, `SystemNotFoundError`,
  `RegisterNotFoundError`, `AuditLogCorruptError`, `PendingChangeError`.

## Engines

Each engine that changes a project takes the storage and an `AuditEngine`. It records
every change in the audit chain inside one unit of work.

- `AuditEngine(storage, actor, signer=None)`: appends hash-chained audit entries. The
  `actor` is an `AuditActor`. With a `signer`, each entry also carries an Ed25519
  signature of its hash.
- `SystemEngine`: `create(system)` and `classify(system_id, category)`.
- `RiskEngine`: `create_register`, `add_risk`, `update_risk`, `upsert_item`,
  `add_mitigation`, `accept_risk`, `set_test_requirements` and `list_risks`. Errors:
  `RiskNotFoundError`, `AmbiguousRiskIdError`. `origin_key` and `UpsertOutcome` describe
  how a repeated assessment matches existing items.
- `AssessEngine`: `AssessEngine()` reads the bundled question bank and patterns
  (`load_questions`, `load_patterns`, `match_patterns`). Pass a directory to read your
  own. `keyword_matches` is the rule a pattern keyword follows.
- `TestDerivationEngine`: `derive(items)` returns the `TestRequirement` list that
  `RiskEngine.set_test_requirements` saves.
- `ValidateEngine`: `run(register)` returns one `GateResult` per gate. Each has a
  `GateStatus` of PASS, WARN or FAIL. `has_failures(results)` is True when any gate
  failed.
- `ExportEngine`: `ExportEngine(registry, audit, storage).export(system_id, fmt, path,
  force=False, signer=None)` checks integrity and the gates, writes the file, records
  the export and returns an `ExportResult`. Errors include `IntegrityError`,
  `ValidationGateError` and `SchemaViolationError`. `PluginRegistry` finds the
  exporters: call `load_all()` first. `build_cross_references` groups risk items by
  the references they cite.

## Integrity and verification

- `check_integrity`: `check_integrity(storage, trusted_keys=None)` returns an
  `IntegrityReport`. `require_intact` raises `IntegrityError` instead.
- `canonical_json` and `document_fingerprint` define the bytes that hashes and register
  fingerprints cover.
- `check_rmf_document`: `check_rmf_document(document, trusted_keys=(), receipts=())`
  checks an exported RMF document, the same check `riskforge verify --file` runs, and
  returns an `RmfCheck`. `RmfCheck.ok` is True when nothing failed, and `findings` lists
  each failure.
- `content_digest` computes an RMF document's digest. `rmf_document` turns a
  `RiskManagementFile` into the document the JSON exporter writes.
  `UnsupportedRmfVersionError` is raised for a schema version this release does not
  read.
- `build_receipt`, `check_receipt` and `receipt_from_document` create and check
  `Receipt` records. A receipt proves that the chain held an entry at a given position.
- `diff_registers`: `diff_registers(old, new)` compares two register documents and
  returns a `RegisterDiff` of added, removed and changed items, with `ItemChange` and
  `FieldChange` details.

## Signing

- `generate_key_pair_pem` makes an Ed25519 key pair as PEM bytes.
- `Ed25519Signer` signs with the private key. `Ed25519Signer.from_file(path)` loads it.
- `key_id_for` names a public key. `load_public_key_b64` reads a public key file.
  `verify_signature` checks one signature.
- `KeyFileError` covers missing, unreadable or wrong-type key files.
- `rmf_signing_message` and `signoff_signing_message` are the exact bytes an RMF
  signature and an approver sign-off cover.

## Models

`AISystem`, `AnnexIIICategory`, `RiskRegister`, `RiskItem`, `RiskDimension`,
`Likelihood`, `Severity`, `Mitigation`, `TestRequirement`, `AuditEntry`, `AuditActor`,
`Receipt`, `RiskManagementFile`, `CrossReference`, `ChainProof`, `RmfSignature`,
`PublicKeyRecord` and `SignOff` are Pydantic models and enums. An exported RMF follows
the bundled JSON Schema `https://aiexponent.com/schemas/riskforge/rmf/1.1.0.json`.

## Example

This program creates a project in `my-project/`, records a system and one risk per
dimension, derives test requirements, exports a signed RMF and checks it. Run it in an
empty directory.

```python
import asyncio
import json
from pathlib import Path

import riskforge.api as rf


async def main() -> None:
    private_pem, _public_pem = rf.generate_key_pair_pem()
    key_file = Path("signing.pem")
    key_file.write_bytes(private_pem)
    key_file.chmod(0o600)
    signer = rf.Ed25519Signer.from_file(key_file)

    store = rf.FileStore(Path("my-project"))
    await store.init_project("my-project", {"created_by": "my-app"})
    audit = rf.AuditEngine(store, rf.AuditActor(type="api", identity="my-app"))

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
    tests = rf.TestDerivationEngine().derive(register.items)
    await risks.set_test_requirements(system_id, tests)

    gates = rf.ValidateEngine().run(await store.read_register(system_id))
    print("Gates passed:", not rf.ValidateEngine().has_failures(gates))

    registry = rf.PluginRegistry()
    registry.load_all()
    exporter = rf.ExportEngine(registry, audit, store)
    result = await exporter.export(system_id, "json", Path("rmf.json"), signer=signer)

    document = json.loads(result.path.read_text(encoding="utf-8"))
    check = rf.check_rmf_document(document, trusted_keys=[signer.public_key_b64])
    print("Signed RMF verified:", check.ok)
    report = await rf.check_integrity(store)
    print("Audit chain intact:", report.ok)


asyncio.run(main())
```

It prints:

```text
Gates passed: True
Signed RMF verified: True
Audit chain intact: True
```

Keep the private key out of version control. A test in the repository runs this
example on every change, so it stays in step with the API.
