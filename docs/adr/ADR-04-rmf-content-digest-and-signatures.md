# ADR-04: RMF Content Digest, Ed25519 Signatures, Receipts and the Chain Proof

**Status:** Proposed
**Date:** October 2026
**Deciders:** Maintainer

## Context

Up to 1.1.3 an exported Risk Management File (RMF, schema 1.0.0) carries one SHA-256, `sha256_hash`, taken over the whole document with `sha256_hash`, `audit_entry_hash` and `signed_by` blanked. `id` and `generated_at` are inside that hash, so two exports of one register never share a digest, and the JSON, PDF and Markdown of one export cannot be matched by digest. `rmf.exported` is recorded before the file is written, so a failed write leaves an audit entry for a file that does not exist. `--sign` runs GnuPG and writes a detached `.asc` file that RiskForge never checks. `riskforge verify --file` checks only the digest, which anyone who edits the file can recompute.

ADR-03 made the audit chain catch most changes to a project, and recorded its limit: someone who rewrites the log and `audit.head.json` together goes undetected, unless a record is kept outside the project. It fixed how an audit entry is signed but added no signer.

AGENTS.md hard rule 5 says any change to the export SHA-256 or to the fields left out of it needs an ADR before the code. This ADR is that record. It defines RMF schema 1.1.0 and its content digest, Ed25519 keys, what each signature signs, receipts, the chain proof embedded in an export, and the order in which an export runs. Files written under schema 1.0.0 keep their rule and still verify.

## Decision

### 1. RMF schema 1.1.0

New exports declare `"rmf_schema_version": "1.1.0"`. The schema files become `src/riskforge/_data/schemas/rmf-1.0.0.schema.json` (the current `rmf.schema.json`, content unchanged except its `$id`) and `rmf-1.1.0.schema.json`. Their `$id` values are `https://aiexponent.com/schemas/riskforge/rmf/1.0.0.json` and `https://aiexponent.com/schemas/riskforge/rmf/1.1.0.json`, the URLs the website serves them from.

Schema 1.1.0 is schema 1.0.0 with these changes:

| Change | Detail |
| --- | --- |
| Removed | `signed_by` and `audit_entry_hash`. The schema forbids extra properties, so a 1.1.0 file that carries either fails validation |
| Added to the register | `test_requirements` (saved by `riskforge tests generate`), and the `accepted_by` and `recorded_by` fields the 2.0 register already holds |
| Added at the top level | `signoffs`, `signatures` and `public_keys` (arrays, empty by default), and `chain_proof` and `receipt` (an object or `null`) |

Up to now the JSON exporter drops `accepted_by` and `recorded_by` from the register so the document fits schema 1.0.0. Under 1.1.0 it keeps them, so the register block of an export is the register exactly as the current model serialises it. Section 6 depends on this.

### 2. Content digest

`sha256_hash` holds the content digest. Which rule applies depends on the declared version:

```python
EXCLUDED_1_1_0 = ("id", "generated_at", "sha256_hash", "signatures",
                  "public_keys", "chain_proof", "receipt")

def content_digest(document: dict) -> str:
    version = document.get("rmf_schema_version")
    if version == "1.0.0":
        source = {**document, "sha256_hash": "", "audit_entry_hash": "", "signed_by": ""}
    elif version == "1.1.0":
        source = {k: v for k, v in document.items() if k not in EXCLUDED_1_1_0}
        source.setdefault("signoffs", [])
    else:
        raise UnsupportedRmfVersionError(version)
    return sha256(canonical_json(source)).hexdigest()
```

- `canonical_json` is the function in ADR-03 section 2: Python's `json.dumps` with sorted keys, separators `(",", ":")` and ASCII escaping. It is not RFC 8785 (JCS).
- For 1.1.0 the digest covers `rmf_schema_version`, `register`, `test_requirements`, `cross_references`, `disclosure` and `signoffs`. `signoffs` is hashed as `[]` when the key is absent, so a file written without the key and one written with an empty list share a digest.
- For 1.0.0 the rule is the one 1.1.3 uses, byte for byte, including when the three blanked keys are absent from the file.
- A document with any other `rmf_schema_version` is refused, not given a digest.

The JSON, PDF and Markdown exports of one register state carry the same digest. Each exporter renders the same `RiskManagementFile`, and the PDF and Markdown show its `sha256_hash`. Two exports of one register state, by the same RiskForge version, share a digest even though their `id`, `generated_at`, chain proof, receipt and signatures differ. The `disclosure` names the RiskForge version and the question bank version, so the same register exported by another release has another digest.

The shared digest also depends on `test_requirements` being saved on the register. Up to now the export derives them afresh, with a new random `id` for each one, on every run.

### 3. Ed25519 keys

`riskforge keygen --output FILE` creates a key pair with the `cryptography` package:

- The private key is written to `FILE` as unencrypted PKCS8 PEM, created with mode 600. The public key goes to `FILE.pub` as SubjectPublicKeyInfo PEM. `keygen` never overwrites either file and exits 3 if one exists.
- Inside RiskForge documents a public key is the standard base64 of its 32 raw bytes.
- `key_id = "ed25519:" + sha256(raw_public_key).hexdigest()[:16]`. The key id is a label for finding a key. Wherever trust is decided, RiskForge compares the full public key, never the key id alone.
- A command that signs (`--sign FILE`) refuses, with exit code 3, a key file that is missing, is not an Ed25519 private key, or on POSIX systems can be read by its group or by others.
- GPG signing is removed. `export --sign` takes a key file. A value that is not a key file, such as a GPG key id, exits 3 with a message that names `riskforge keygen`. No `.asc` file is written.

`cryptography` is added with a bounded version range, and its licence is checked under AGENTS.md hard rule 7 when it is added.

### 4. What each signature signs

Every signature is Ed25519 over a message that starts with a fixed domain prefix ending in `\n`, so a signature made for one kind of record cannot be presented as another.

| Signature | Stored in | Message signed |
| --- | --- | --- |
| RMF signature | `signatures[]` of a 1.1.0 file: `key_id`, `algorithm` (`"ed25519"`), `signed_at`, `signature` | `b"riskforge.rmf.v1\n"` + the hex content digest |
| Receipt | `signature` of a receipt | `b"riskforge.receipt.v1\n"` + `canonical_json` of the receipt without `public_key` and `signature` |
| Sign-off | `signature` of an entry in `signoffs[]` | `b"riskforge.signoff.v1\n"` + `canonical_json` of the sign-off without `signature` |
| Audit entry | `signature` of an audit entry | `b"riskforge.audit-entry.v1\n"` + the hex `entry_hash`, as ADR-03 section 2 fixes |

- The RMF signature signs the content digest, so one signature covers every format of one register state. `signed_at` is not part of the signed message.
- The receipt message is the receipt as the `Receipt` model dumps it in JSON mode. Fields that are `None` appear as `null`, unlike audit entries, where ADR-03 leaves them out.
- The audit entry rule does not change ADR-03. `AuditEngine` accepts an optional signer. When one is given, each entry carries `key_id`, which its hash covers, and a signature over its hash, which its hash does not cover. The free CLI does not sign audit entries in 2.0. An entry that has `key_id` and no `signature`, or the reverse, fails the integrity check and fails `verify --file`.
- Sign-offs come from RiskForge Team. The free CLI does not create them. `verify --file` checks them.
- `public_keys[]` of a 1.1.0 file holds `key_id`, `algorithm` and `public_key` for every key that signed the file, its receipt, or an entry in its chain proof. A file whose chain proof holds an entry signed by a key the exporter was not given is not written.

### 5. Receipts

A receipt records that the project chain held a given entry at a given `seq`:

| Field | Meaning |
| --- | --- |
| `receipt_version` | `"1"` |
| `system_id` | The system the receipt was taken for |
| `seq`, `entry_hash` | The last entry of the project chain when the receipt was taken |
| `register_fingerprint` | The latest fingerprint the chain records for that system, or `null` |
| `issued_at` | When the receipt was made, from the local clock |
| `key_id`, `public_key`, `signature` | Present only when the receipt is signed |

- `riskforge receipt SYSTEM_ID [--output FILE] [--sign KEYFILE]` runs the ADR-03 integrity check first and exits 2 if it fails. With `--output` it writes the receipt with mode 600 and never overwrites a file. Without it, it prints the receipt as JSON.
- `riskforge verify --receipt FILE` (repeatable) takes a receipt file or an exported 1.1.0 RMF and reads its `receipt` block. The check fails with exit code 2 when the chain has no entry at the receipt's `seq` ("truncated or replaced") or holds a different `entry_hash` there ("rewritten").
- A signed receipt fails when its `key_id` does not match its `public_key` or its signature does not verify. With `--trusted-key PUBFILE` (repeatable) its public key must be one of the trusted keys, and an unsigned receipt fails.
- Every export embeds a receipt for the last entry in its chain proof, signed when the export is signed.

### 6. Chain proof

A 1.1.0 export embeds `chain_proof`: `scope` and `entries`. The chain is one per project (ADR-03), and a subset of it cannot be checked link by link, so PR 3 always writes `"scope": "project"` with every entry of the project chain up to the export. The `rmf.exported` entry of the export itself is recorded after the file is written (section 7), so it is never in the file. The value `"system"` is reserved for a backend that keeps one chain per system.

`riskforge verify --file FILE` checks a 1.1.0 document in this order, and reports every failure it finds:

1. The document validates against the schema its `rmf_schema_version` names, and `sha256_hash` equals the content digest.
2. Each embedded public key matches its `key_id`.
3. Each RMF signature verifies with its embedded key. With `--trusted-key`, each one must also come from a trusted key and the file must carry at least one.
4. Each sign-off's signature verifies with its embedded key, and its `register_fingerprint` equals the fingerprint of the file's `register` block.
5. The chain proof entries pass the ADR-03 link and hash check from `seq` 0. Every signed entry verifies with its embedded key. The last `register_fingerprint` the chain proof records for the register's system equals `document_fingerprint(register)` of the file.
6. The embedded receipt passes section 5 against the chain proof, with the trusted keys when given. Its `system_id` must be the register's system, and its `register_fingerprint`, when present, must equal the fingerprint of the register block.
7. Each `--receipt FILE` given with `--file` passes section 5 against the chain proof. A receipt taken from an older export checks against a newer export of the same project.

Any failure exits 2. A document that is not JSON, or declares a version this RiskForge does not read, exits 3. A 1.0.0 document gets step 1 only, as in 1.1.3.

Step 5 compares a fingerprint of the register block with fingerprints the chain took from the stored `register.yaml` (ADR-03 section 3). The two agree because the register block is the register as the current model serialises it (section 1), and the export makes the stored register match that form before it records the chain proof (section 7).

What each record catches when the file is checked alone:

| Record | Catches | Does not catch |
| --- | --- | --- |
| Content digest | A change to the content by someone who did not recompute the digest | Anyone can recompute it |
| Chain proof | A register block that is not the state the chain recorded last, and edited, missing or reordered entries | A chain proof rebuilt to agree with an edited register, since the algorithm is public |
| Embedded receipt | A chain proof that no longer holds the head the export recorded | Unless it is signed by a trusted key, a receipt rebuilt along with the chain proof |
| RMF signature with `--trusted-key` | Any change to the content, since the trusted key signed the digest | Changes to the blocks the digest leaves out, which steps 5 and 6 bind to the content |
| RMF signature without `--trusted-key` | Nothing about who signed | Anyone can sign with a new key and embed it |

A file signed by a trusted key therefore binds three things. The signature covers the content, the signed receipt covers the chain proof up to its `seq`, and the fingerprint check of step 5 ties the chain proof to the content.

Against the project, `verify --receipt` with a receipt kept outside the project catches the case ADR-03 cannot: a log cut back or rebuilt, with `audit.head.json` rewritten to match, so that plain `verify` passes. It catches this only for entries up to the receipt's `seq`.

### 7. Export order

`ExportEngine.export(system_id, fmt, output_path, force=..., signer=...)` builds the RMF itself. The CLI no longer builds it. Everything happens in one unit of work opened through `AuditEngine.unit_of_work()`, so the ADR-03 integrity check runs once, after the lock and recovery, before anything is staged:

1. **Integrity check.** A project that fails it exits 2, and nothing is written.
2. **Gates.** Unless `--force` is given, a FAIL gate stops the export, and nothing is written.
3. **`register.checkpoint`.** If the fingerprint of the register as the current model serialises it differs from the latest fingerprint the chain records for the system, the engine writes the register in that form and records `register.checkpoint`, with payload `{"riskforge_version": ...}` and the fingerprint of the stored result. This happens for a register last written by 1.1.3 or by an older model. If the stored register still does not match the serialised form, because a value does not survive the YAML round trip (ADR-03 section 3), the export stops without writing a file. On the file store the checkpoint commits when it is recorded, so it stays even if a later step fails. It records a rewrite that changes no value.
4. **Build.** The engine builds the content and its digest, then the chain proof (every entry so far), the receipt for the last of them, the RMF signature when a signer is given, and `public_keys`. The document must validate against schema 1.1.0.
5. **Atomic write.** The exporter renders the file. It is written to a temporary file in the target directory, flushed to disk, set to mode 600 and renamed over the target. A render that fails, a schema violation or a missing or unwritable directory leaves no file and records no `rmf.exported`.
6. **`rmf.exported`.** Recorded only after the rename, with payload `{"export_id", "format", "sha256", "file_sha256"}`. `sha256` is the content digest. `file_sha256` is the SHA-256 of the bytes written, so a file of any format can be matched to its entry by hashing it.

`register.checkpoint` is a new event. Like every `register.*` event, the integrity check treats it as one that changes a register. Adding `file_sha256` to the `rmf.exported` payload adds a key to an event 1.1.3 already writes. ADR-03 is not edited. This ADR records both changes.

### 8. Timestamps

Founder decision, 2026-10-12: the times that belong to the act of exporting live only in blocks the content digest leaves out. These are `generated_at`, `signed_at` in each RMF signature, `issued_at` in the receipt, and the `timestamp` of each chain proof entry. So two exports of one register state share a digest and can be compared by it.

The digest still covers the times that are part of the state being exported: the dates in the register, and `totp_verified_at` and `signed_at` inside each sign-off. A sign-off is fixed once made, so these do not change from one export to the next.

AGENTS.md hard rule 2 lists `id`, `generated_at` and the 1.1.0 provenance blocks, with the times inside them, as the known exceptions to reproducible export content.

### 9. Compatibility

- A 1.0.0 file written by 1.1.3 validates against `rmf-1.0.0.schema.json` and verifies under 2.0 with the 1.1.3 rule. `tests/fixtures/v1_1_3_project/rmf.json` is the reference. Its detached GPG signature, if any, is not checked by RiskForge, as before.
- The 1.0.0 schema's content does not change. Its `$id` moves from `https://schemas.aiexponent.com/riskforge/rmf/v1.0.0`, which does not resolve, to its published URL. No digest depends on the schema's `$id`.
- RiskForge 2.0 writes only 1.1.0 files. RiskForge 1.1.3 hashes every key of a 1.1.0 file except its three blanked ones, so its `verify --file` reports a 1.1.0 file as tampered. Downgrade is not supported, as in ADR-03.
- `export --sign` changes meaning from a GPG key id to a key file path. Scripts that pass a GPG id exit 3 with a message, and no file is written.
- Audit chains, register fingerprints and the head file do not change. Audit entry signatures use the fields and the message ADR-03 already fixed.

## Rationale

- **Leaving the provenance blocks out of the digest** gives one digest for one register state, whatever the format and however often it is exported. Each block either verifies itself (signatures, receipt, chain proof) or describes the act of exporting (id, times). Hashing them would make every export unique and would make the signature circular, since the signature, receipt and chain proof are computed after the digest.
- **Recording `rmf.exported` after the write** means the log never names a file that was not written. The price is that the file cannot carry its own export entry's hash, so `audit_entry_hash` goes. The chain proof and receipt carry the chain head instead.
- **Ed25519 with local key files** works offline, has no external binary or keyring state, behaves the same on every platform CI runs, and embeds the signature in the file, so it cannot be separated from it.
- **Comparing full public keys** keeps trust independent of the 64-bit key id, which someone could deliberately collide.
- **Domain prefixes** stop a signature over one kind of record from verifying as another kind.
- **Receipts** are the record kept outside the project that ADR-03 said was missing. They need no server and no network.
- **The checkpoint** makes the chain proof end at the exact state the file holds, including for registers written before 2.0.

## Alternatives Considered

- **Keep the 1.1.3 rule for 1.1.0.** Every export would get its own digest, the three formats could not share one, and a signature over the digest could not cover a receipt or chain proof computed after it.
- **Put `signed_at` inside the digest.** It would date the content, but two exports of one register would no longer share a digest. Rejected by the founder decision of 2026-10-12. The signing time stays in the signature block.
- **Keep recording `rmf.exported` before the write.** That keeps `audit_entry_hash`, but a failed write leaves an entry for a file that does not exist, the defect this ADR fixes.
- **Keep GPG.** It needs an external binary and keyring state that tests cannot reproduce offline, and its detached `.asc` file is easily separated from the export. RiskForge never checked it.
- **Sign the file bytes.** The PDF and Markdown bytes differ from the JSON bytes, so each format would need its own signature, and an embedded signature cannot cover the bytes that hold it.
- **RFC 8785 (JCS) for the digest.** That would add a second canonical form next to the one ADR-03 fixed for the audit chain. One form for every hash RiskForge computes is easier to check.
- **PyNaCl instead of `cryptography`.** It would add libsodium for no gain.
- **Anchor the chain head in a public transparency log.** That needs a network call, which AGENTS.md hard rule 1 forbids in the free CLI. RiskForge Team may offer it as an opt-in.
- **A chain proof of one system's entries only.** The chain is one per project, so a subset cannot be checked link by link.

## Trade-offs Accepted

- The content digest proves only that the content is consistent with itself. Without `--trusted-key`, a valid signature proves only that whoever holds the embedded key signed. The verifier has to get the signer's public key by some other route.
- Private keys are stored unencrypted, protected only by file mode. The mode check applies on POSIX systems only. There is no revocation. Rotation works because entries name their `key_id`, but PR 3 does not test it.
- `signed_at` and `issued_at` come from the local clock, and nothing checks them.
- The chain proof holds the whole project log, so an export shows the audit entries of every system in the project, with actor identities and payloads, and grows with the log.
- Only the JSON export can be checked with `verify --file`. A PDF or Markdown file is checked by comparing the digest it shows with a verified JSON export of the same state, or by hashing it and comparing with `file_sha256` in the log.
- If the process stops between the rename and the `rmf.exported` entry, a file exists with no entry for it. The file still verifies alone, since its chain proof ends before the export.
- A checkpoint recorded during an export that then fails stays in the log.
- A receipt proves only the entries up to its `seq`. `verify --receipt` does not compare a receipt's `register_fingerprint` with the project's current register, which may have changed since, for good reasons.
- As in ADR-03, a receipt or sign-off edited in a way that leaves every field value the same after parsing (for example `+00:00` in place of `Z`) is not detected, and does not change what it records.
- A document that declares an unknown `rmf_schema_version` exits 3, not 2.
- Canonical JSON follows Python's `json.dumps`, not a published standard.

## Enforcement

PR 3 adds these tests:

- `tests/unit/test_signing.py` and `tests/integration/test_keygen.py`: keys, key ids, signatures, mode 600, no overwrite.
- `tests/unit/test_receipts.py` and `tests/integration/test_receipt_command.py`: a receipt catches a log cut back with the head file rewritten, which plain `verify` passes; edited, untrusted and unsigned receipts; signed audit entries.
- `tests/contract/test_rmf_schemas.py`: both schemas and their `$id` values, the 1.1.3 file still validating and matching its digest, 1.1.0 rejecting `signed_by` and `audit_entry_hash`, the digest ignoring each left-out field and covering the content and sign-offs.
- `tests/integration/test_export_command.py`: one digest across JSON, PDF and Markdown; `rmf.exported` after the write, with `file_sha256`; nothing written or recorded after a failed render or an unwritable path; signed exports; a GPG key id refused; a 1.1.3 project exporting with a checkpoint.
- `tests/integration/test_verify_file.py`: untouched 1.0.0 and 1.1.0 files pass; edits to the register, chain proof, receipt, a signature, a sign-off or the retired fields fail with exit code 2; `--trusted-key` and `--receipt` with `--file`.
- `tests/integration/test_v113_compat.py`: the 1.1.3 fixture still verifies.

## Consequence

Any later change to the content digest, to the fields it leaves out, to a signing message or its domain prefix, to the `key_id` rule or to the receipt fields needs a new ADR, and a new RMF schema version or prefix version for the records it changes. Files written under 1.0.0 and 1.1.0 must keep verifying with the rules above.
