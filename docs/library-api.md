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
  somewhere other than files. Inside its `unit_of_work()`, a register or system write
  and the audit entry that records it become visible together. To change a project,
  call the engines below, or open `AuditEngine.unit_of_work()` for a change of your
  own. Do not open `storage.unit_of_work()` directly: that skips the integrity check,
  and the change is refused when it records its entry.
- `FileStore`: the file-based backend the CLI uses (`.riskforge/` plus
  `riskforge.yaml`). `FileStore(path, read_only=True)` checks a project without writing
  to it.
- Errors: `ProjectNotFoundError`, `ProjectExistsError`, `SystemNotFoundError`,
  `RegisterNotFoundError`, `AuditLogCorruptError`, `PendingChangeError`.

## Engines

Each engine that changes a project takes the storage and an `AuditEngine`. It records
every change in the audit chain inside one unit of work.

- `AuditEngine(storage, actor, signer=None)`: appends hash-chained audit entries. The
  `actor` is an `AuditActor`. With a `signer`, each entry also carries an Ed25519
  signature of its hash. `unit_of_work()` opens a change only when the project passes
  its integrity check. `read_register(system_id)` and `read_system(system_id)` read a
  file and, inside a checked change, raise `IntegrityError` when it changed after the
  check.
- `SystemEngine`: `create(system)` and `classify(system_id, category)`.
- `RiskEngine`: `create_register`, `add_risk`, `update_risk`, `upsert_item`,
  `add_mitigation`, `accept_risk`, `set_test_requirements` and `list_risks`. Errors:
  `RiskNotFoundError`, `AmbiguousRiskIdError`. `upsert_item` returns an `UpsertResult`
  (`outcome`, `item`, `previous`, `matches`). `origin_key` and `UpsertOutcome` describe
  how a repeated assessment matches existing items.
- `AssessEngine`: `AssessEngine()` reads the bundled question bank and patterns
  (`load_questions`, `load_patterns`, `match_patterns`). Pass a directory to read your
  own. `keyword_matches` is the rule a pattern keyword follows.
- `TestDerivationEngine`: `derive(items)` returns the `TestRequirement` list that
  `RiskEngine.set_test_requirements` saves.
- `ValidateEngine`: `run(register)` returns one `GateResult` per gate. Each has a
  `GateStatus` of PASS, WARN or FAIL. `has_failures(results)` is True when any gate
  failed.
- `ExportEngine`: `ExportEngine(registry, audit, storage)`. Its method is
  `export(system_id, fmt, output_path, *, force=False, signer=None, public_keys=(),
  export_id=None)`. Everything after `output_path` is keyword-only. It checks integrity
  and the gates (skipped with `force=True`), writes the file, records the export and
  returns an `ExportResult`. `signer` is an `Ed25519Signer` that signs the file and its
  receipt. `public_keys` are base64 public keys of audit entries signed outside this
  engine, which the file must embed. `export_id` is a `UUID` to use as the file's `id`
  instead of a new random one. `IntegrityError` means the project failed its check.
  Every other refusal is an `ExportError`, such as `ValidationGateError` or
  `SchemaViolationError`; nothing is written or recorded then. `PluginRegistry` finds
  the exporters: call `load_all()` first. `build_cross_references` groups risk items
  by the references they cite.

## Integrity and verification

- `check_integrity_settled`: `check_integrity_settled(storage, *, trusted_keys=None,
  repeats=3, pause=0.25)` is the check `riskforge verify` runs. It takes no lock. While
  a writer is busy it waits `pause` seconds and checks again, up to `repeats` times,
  then raises `ChangeInProgressError`. Use it to check a project another process may be
  changing, or a read-only copy.
- `check_integrity`: `check_integrity(storage, *, trusted_keys=None)` runs the check
  once, with no retry. Use it when nothing else writes to the project, such as inside a
  change you opened with `AuditEngine.unit_of_work()`. `require_intact` raises
  `IntegrityError` instead of returning a failed report.
- `IntegrityReport`: `ok` is True when `errors` is empty. `warnings` lists what the
  check could not cover, such as a register last written before RiskForge 2.0, or signed
  entries not checked because no trusted key was given. `ok` can be True with warnings.
  `strict()` returns the report with its warnings about missing coverage counted as
  errors, as `riskforge verify --strict` does.
- `reads_checked_against`: `with reads_checked_against(storage, report):` compares each
  `AuditEngine.read_register` and `read_system` call in the block with what the check
  behind `report` read, and raises `IntegrityError` for a file changed since. Use it to
  read a project after `check_integrity_settled` without taking a lock.
- `canonical_json` and `document_fingerprint` define the bytes that hashes and register
  fingerprints cover.
- `read_rmf_file`: `read_rmf_file(path)` reads an exported RMF file strictly and returns
  the document. It raises `StrictJsonError` for a duplicate key, a non-finite number or
  nesting deeper than RiskForge writes, `NumberTooLongError` for an integer too long to
  read, and `RmfFileError` for a file that cannot be read, is not JSON or is not a JSON
  object. RiskForge never writes the first two, so treat them as a failed check. Read
  files with it, not `json.load`: with a duplicate key, `json.load` keeps one of the
  values, and an edited file can then pass.
- `check_rmf_document`: `check_rmf_document(document, trusted_keys=(), receipts=())`
  checks a document from `read_rmf_file` and returns an `RmfCheck`. `trusted_keys` are
  base64 public keys, such as `load_public_key_b64(Path("signing.pem.pub"))`. `receipts`
  are `(label, receipt)` pairs from `read_receipt_file`. `read_rmf_file` followed by
  `check_rmf_document` with the same keys and receipts is the check `riskforge verify
  --file FILE --trusted-key PUBFILE --receipt RECEIPT` runs.
- `RmfCheck`: `findings` lists each failure and `notes` say what a pass proves.
  `verified` is True when nothing failed and trusted keys were given, so a trusted key
  signed the file. This is when `riskforge verify --file` prints "RMF integrity
  verified". `ok` is True when nothing failed. Without trusted keys, `ok` means only
  that the file is internally consistent: anyone can build a file with its own chain
  proof, receipt and signatures from a key of their own, and it passes. Check
  `verified` to accept a file as genuine.
- `content_digest` computes an RMF document's digest. `rmf_document` turns a
  `RiskManagementFile` into the document the JSON exporter writes.
  `UnsupportedRmfVersionError` is raised for a schema version this release does not
  read.
- `build_receipt`, `check_receipt` and `receipt_from_document` create and check
  `Receipt` records. A receipt proves that the chain held an entry at a given position.
  `read_receipt_file(path)` reads a receipt file, or an RMF file's receipt, strictly. It
  raises `InvalidReceiptError` for a receipt that is refused, including a duplicate key,
  which counts as a failed check, and `ReceiptFileError` for a file that cannot be read
  or is not a receipt or RMF file.
- `diff_registers`: `diff_registers(old, new)` compares two register documents and
  returns a `RegisterDiff` of added, removed and changed items, with `ItemChange` and
  `FieldChange` details.

## Signing

- `write_key_pair`: `write_key_pair(path)` creates an Ed25519 key pair as `riskforge
  keygen` does: the private key in `path` (mode 600 on Linux and macOS) and the public
  key in `path.pub`. It returns the base64 public key and never overwrites a file.
  `generate_key_pair_pem` returns a key pair as PEM bytes instead.
- `Ed25519Signer` signs with the private key. `Ed25519Signer.from_file(path)` loads it
  and, as `--sign` does, refuses a symbolic link, a file that is not a regular file and,
  on Linux and macOS, a key its group or other users can access.
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
dimension, derives test requirements, exports a signed RMF and checks it as
`riskforge verify --file rmf.json --trusted-key signing.pem.pub` does. Run it in an
empty directory.

```python
import asyncio
from pathlib import Path

import riskforge.api as rf


async def main() -> None:
    rf.write_key_pair(Path("signing.pem"))
    signer = rf.Ed25519Signer.from_file(Path("signing.pem"))

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
    register = await audit.read_register(system_id)
    tests = rf.TestDerivationEngine().derive(register.items)
    await risks.set_test_requirements(system_id, tests)

    gates = rf.ValidateEngine().run(await audit.read_register(system_id))
    print("Gates passed:", not rf.ValidateEngine().has_failures(gates))

    registry = rf.PluginRegistry()
    registry.load_all()
    exporter = rf.ExportEngine(registry, audit, store)
    result = await exporter.export(system_id, "json", Path("rmf.json"), signer=signer)

    # The public key file you trust, as you would pass it to --trusted-key.
    trusted = [rf.load_public_key_b64(Path("signing.pem.pub"))]
    document = rf.read_rmf_file(result.path)
    check = rf.check_rmf_document(document, trusted_keys=trusted)
    print("RMF verified with the trusted key:", check.verified)
    report = await rf.check_integrity_settled(store)
    print("Audit chain intact:", report.ok)


asyncio.run(main())
```

It prints:

```text
Gates passed: True
RMF verified with the trusted key: True
Audit chain intact: True
```

Keep the private key out of version control. In a real check, trust the public key file
you received from the signer, not one read from the file being checked. A test in the
repository runs this example on every change, so it stays in step with the API.
