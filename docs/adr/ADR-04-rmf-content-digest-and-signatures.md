# ADR-04: RMF Content Digest, Ed25519 Signatures, Receipts and the Chain Proof

**Status:** Proposed
**Date:** October 2026
**Deciders:** Maintainer

## Context

Up to 1.1.3 an exported Risk Management File (RMF, schema 1.0.0) carries one SHA-256, `sha256_hash`, taken over the whole document with `sha256_hash`, `audit_entry_hash` and `signed_by` blanked. `id` and `generated_at` are inside that hash, so two exports of one register never share a digest, and the JSON, PDF and Markdown of one export cannot be matched by digest. `rmf.exported` is recorded before the file is written, so a failed write leaves an audit entry for a file that does not exist. `--sign` runs GnuPG and writes a detached `.asc` file that RiskForge never checks. `riskforge verify --file` checks only the digest, which anyone who edits the file can recompute.

ADR-03 made the audit chain catch most changes to a project, and recorded its limit: someone who rewrites the log and `audit.head.json` together goes undetected, unless a record is kept outside the project. It fixed how an audit entry is signed but added no signer.

AGENTS.md hard rule 5 says any change to the export SHA-256 or to the fields left out of it needs an ADR before the code. This ADR is that record. It defines RMF schema 1.1.0 and its content digest, Ed25519 keys, what each signature signs and how its key is found, receipts, the chain proof embedded in an export, and the order in which an export runs. Files written under schema 1.0.0 keep their rule and still verify.

### Relation to ADR-03

ADR-03 section 7 lists what it did not change. For RMF 1.1.0 files and the exports that write them, this ADR supersedes its first three bullets: the export SHA-256 and its blanked fields (section 2 here), `riskforge verify --file` behaviour (section 6), and the `rmf.exported` payload, which gains `file_sha256`, next to the new `register.checkpoint` event (section 7). For 1.0.0 files those bullets still hold. ADR-03's chain hashing, register fingerprints, head file, unit of work and integrity check are unchanged. ADR-03 is not edited.

## Decision

### 1. RMF schema 1.1.0

New exports declare `"rmf_schema_version": "1.1.0"`. The schema files become `src/riskforge/_data/schemas/rmf-1.0.0.schema.json` (the current `rmf.schema.json`, content unchanged except its `$id`) and `rmf-1.1.0.schema.json`. Their `$id` values are `https://aiexponent.com/schemas/riskforge/rmf/1.0.0.json` and `https://aiexponent.com/schemas/riskforge/rmf/1.1.0.json`, the URLs the website serves them from.

Schema 1.1.0 is schema 1.0.0 with these changes:

| Change | Detail |
| --- | --- |
| Removed | `signed_by` and `audit_entry_hash`. The schema forbids extra properties, so a 1.1.0 file that carries either fails validation |
| Added to the register | `test_requirements` (saved by `riskforge tests generate`), and the `accepted_by` and `recorded_by` fields the 2.0 register already holds |
| Added at the top level | `signoffs`, `signatures` and `public_keys` (arrays, empty by default), and `chain_proof` and `receipt` (required objects) |

Every object in the provenance blocks has `additionalProperties: false` in schema 1.1.0, so it can hold only the fields this ADR defines: each item of `signatures[]`, `public_keys[]` and `signoffs[]`, the `chain_proof` object and each of its entries, and the `receipt` object. A chain proof entry may hold the optional fields ADR-03 section 1 defines, left out when absent, and no others.

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

**Reading RMF and receipt files.** `verify` reads an RMF file, and a receipt file, with `json.loads` and two hooks. An `object_pairs_hook` rejects any object, at any depth, that holds the same key twice. A `parse_constant` hook rejects `NaN`, `Infinity` and `-Infinity`, and a `parse_float` hook rejects any number that parses to a value that is not finite, such as `1e400`, which Python would otherwise read as infinity and write back as `Infinity`. Python keeps the last of two duplicate keys, other parsers may keep the first, so a file with duplicates could show one value to a reader and hash another. RiskForge never writes either form, so a file that holds one fails with exit code 2. Arrays and objects nested more than 64 levels deep fail the same way: RiskForge writes about seven levels, and a value nested a few hundred levels deep exhausts the recursion of the parser or of the entry hashing. The digest is computed only over a document read this way.

The JSON, PDF and Markdown exports of one register state carry the same digest. Each exporter renders the same `RiskManagementFile`, and the PDF and Markdown show its `sha256_hash`. Two exports of one register state, by the same RiskForge version, share a digest even though their `id`, `generated_at`, chain proof, receipt and signatures differ. The `disclosure` names the RiskForge version and the question bank version, so the same register exported by another release has another digest.

The shared digest also depends on `test_requirements` being saved on the register. Up to now the export derives them afresh, with a new random `id` for each one, on every run.

### 3. Ed25519 keys

`riskforge keygen --output FILE` creates a key pair with the `cryptography` package:

- The private key is written to `FILE` as unencrypted PKCS8 PEM, created with mode 600. The public key goes to `FILE.pub` as SubjectPublicKeyInfo PEM. `keygen` never overwrites either file and exits 3 if one exists.
- Inside RiskForge documents a public key is the standard base64, with padding, of its 32 raw bytes. A signature is the standard base64 of its 64 raw bytes. Both are decoded strictly (`base64.b64decode(value, validate=True)`), and a value that does not decode, or decodes to the wrong length, fails.
- `key_id = "ed25519:" + sha256(raw_public_key).hexdigest()[:16]`. The key id is a label for finding a key. Wherever trust is decided, RiskForge compares the decoded raw public key bytes, never the key id alone and never the base64 text.
- `--trusted-key PUBFILE` reads a SubjectPublicKeyInfo PEM file. A file that is not an Ed25519 public key exits 3. The trusted set is the raw bytes of each key given.
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
- The receipt message is the receipt as the `Receipt` model dumps it in JSON mode. Fields that are `None` appear as `null`, unlike audit entries, where ADR-03 leaves them out. `key_id` is part of the message.
- The audit entry rule does not change ADR-03. `AuditEngine` accepts an optional signer. When one is given, each entry carries `key_id`, which its hash covers, and a signature over its hash, which its hash does not cover. The free CLI does not sign audit entries in 2.0. An entry that has `key_id` and no `signature`, or the reverse, fails the integrity check and fails `verify --file`.
- `public_keys[]` of a 1.1.0 file holds `key_id`, `algorithm` and `public_key` for every key that signed the file, a sign-off, its receipt, or an entry in its chain proof. A file whose chain proof holds an entry signed by a key the exporter was not given is not written.

**Sign-offs.** Sign-offs come from RiskForge Team. The free CLI does not create them, and `verify --file` checks them. A sign-off has exactly these fields, all required except `comment`:

| Field | Meaning |
| --- | --- |
| `approver` | Who decided, as RiskForge Team records them |
| `decision` | `"approved"`, `"rejected"` or `"changes_requested"` |
| `comment` | Free text, `""` by default |
| `version_number` | The register version decided on, 1 or more |
| `register_fingerprint` | The ADR-03 fingerprint of the register decided on |
| `totp_verified_at` | When the approver's second factor was checked |
| `signed_at` | When the sign-off was signed |
| `key_id` | The key that signed it |
| `signature` | Ed25519 signature over the sign-off message |

The message is every field above except `signature`, taken from the model dumped in JSON mode, so every field is present (`comment` included, as `""` when not given) and a missing comment and an empty one give the same message. `key_id` is signed, so a sign-off cannot be moved to another key's name.

**Key resolution.** `verify` finds the key for every signature the same way:

1. The `key_id` values in `public_keys[]` are unique. A file with two records for one key id fails.
2. Each record's `algorithm` is `"ed25519"`, its `public_key` decodes to 32 bytes, and its `key_id` equals the key id derived from those bytes. A record that fails any of these fails.
3. Each RMF signature, sign-off, embedded receipt and signed chain proof entry names a `key_id`. Its key is the `public_keys[]` record with that key id. A `key_id` with no record fails. Each RMF signature's `algorithm` must be `"ed25519"`.
4. The embedded receipt also carries its own `public_key`. Decoded, it must equal the raw bytes of the record its `key_id` resolves to.
5. A receipt read from its own file has no `public_keys[]`. Its key is its own `public_key`, and its `key_id` must equal the key id derived from it.
6. With `--trusted-key`, the key compared with the trusted set is the key the signature was verified with in the steps above, as raw bytes. No second lookup is made.

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
- `riskforge verify --receipt FILE` (repeatable) takes a receipt file or an exported 1.1.0 RMF and reads its `receipt` block. The check fails with exit code 2 when the chain has no entry at the receipt's `seq` ("truncated or replaced") or holds a different `entry_hash` there ("rewritten"). It also fails when the receipt's `register_fingerprint` is not the last fingerprint the chain records for the receipt's `system_id` at or before its `seq`, where both must be `null` if the chain records none.
- A signed receipt fails when its key does not resolve (section 4) or its signature does not verify. With `--trusted-key PUBFILE` (repeatable) the key it was verified with must be one of the trusted keys, and an unsigned receipt fails.
- Every export embeds a receipt whose `seq` and `entry_hash` are those of the last entry in its chain proof, signed when the export is signed.

### 6. Chain proof

A 1.1.0 export embeds `chain_proof`: `scope` and `entries`. The chain is one per project (ADR-03), and a subset of it cannot be checked link by link, so PR 3 always writes `"scope": "project"` with every entry of the project chain up to the export. The `rmf.exported` entry of the export itself is recorded after the file is written (section 7), so it is never in the file. The value `"system"` is reserved for a backend that keeps one chain per system.

`riskforge verify --file FILE` checks a 1.1.0 document in this order, and reports every failure it finds:

1. The file is read as section 2 requires, with duplicate keys and `NaN` or `Infinity` refused. The document validates against the schema its `rmf_schema_version` names, and `sha256_hash` equals the content digest.
2. `public_keys[]` passes section 4 key resolution steps 1 and 2.
3. Each RMF signature resolves its key (section 4) and verifies. With `--trusted-key`, the file must carry at least one RMF signature, and each one's key must be a trusted key.
4. Each sign-off resolves its key and its signature verifies, and its `register_fingerprint` equals the fingerprint of the file's `register` block. With `--trusted-key`, each sign-off's key must be a trusted key.
5. The chain proof holds at least one entry, and its entries pass the ADR-03 link and hash check from `seq` 0. An entry that has `key_id` without `signature`, or the reverse, fails. Every signed entry resolves its key and verifies. The chain proof must record a `register_fingerprint` for the register's system, and the last one it records must equal `document_fingerprint(register)` of the file. An empty chain proof, or one with no fingerprint for the system, fails.
6. The embedded receipt's `seq` and `entry_hash` equal those of the last chain proof entry. Its `system_id` is the register's system, and its `register_fingerprint` is present and equals the fingerprint of the register block. When it is signed, it resolves its key (section 4 steps 3 and 4) and verifies. With `--trusted-key`, it must be signed and its key must be a trusted key.
7. Each `--receipt FILE` given with `--file` is read as section 2 requires and passes section 5 against the chain proof, with the trusted keys when given. A receipt taken from an older export checks against a newer export of the same project.

Any failure exits 2. A document that is not JSON, or declares a version this RiskForge does not read, exits 3.

A 1.0.0 document cannot carry a signature, a chain proof or a receipt. Plain `verify --file` gives it step 1 only, as in 1.1.3, and says that only the content digest was checked and that the file declares RMF schema 1.0.0. With `--trusted-key` or `--receipt`, a 1.0.0 document fails with exit code 2 and the message "RMF schema 1.0.0 cannot carry a signature". Without this rule, someone could set `rmf_schema_version` to `1.0.0`, drop the 1.1.0 blocks, edit the register, recompute the 1.0.0 digest and pass a check the caller meant to require a trusted signature.

Step 5 compares a fingerprint of the register block with fingerprints the chain took from the stored `register.yaml` (ADR-03 section 3). The two agree because the register block is the register as the current model serialises it (section 1), and the export makes the stored register match that form before it builds the chain proof (section 7).

What each record catches when the file is checked alone:

| Record | Catches | Does not catch |
| --- | --- | --- |
| Content digest | A change to the content by someone who did not recompute the digest | Anyone can recompute it |
| Chain proof | A register block that is not the state the chain recorded last, and edited, missing or reordered entries | A chain proof rebuilt to agree with an edited register, since the algorithm is public |
| Embedded receipt | A chain proof whose last entry is not the one the receipt names, including entries added after it | Unless it is signed by a trusted key, a receipt rebuilt along with the chain proof |
| RMF signature with `--trusted-key` | Any change to the content, since the trusted key signed the digest | Changes to the blocks the digest leaves out, which steps 5 and 6 bind to the content |
| RMF signature without `--trusted-key` | Nothing about who signed | Anyone can sign with a new key and embed it |
| 1.0.0 refused with `--trusted-key` or `--receipt` | A 1.1.0 file rewritten as 1.0.0 with its provenance dropped and its digest recomputed | The same file under plain `verify --file`, which says only the digest was checked |

A file that passes with `--trusted-key` therefore binds three things. The RMF signature covers the content through its digest. The receipt, signed by a trusted key, names the last chain proof entry, and since each entry's hash covers the hash of the one before it, the receipt covers every entry of the chain proof and no entry can follow it unsigned. The fingerprint check of step 5 ties the chain proof to the register block. What no signature covers is `id`, `generated_at`, the `signed_at` of each RMF signature and the order of `signatures[]` and `public_keys[]`, none of which changes what the file records.

Against the project, `verify --receipt` with a receipt kept outside the project catches the case ADR-03 cannot: a log cut back or rebuilt, with `audit.head.json` rewritten to match, so that plain `verify` passes. It catches this only for entries up to the receipt's `seq`.

### 7. Export order

`ExportEngine.export(system_id, fmt, output_path, force=..., signer=...)` builds the RMF itself. The CLI no longer builds it. Everything happens in one unit of work opened through `AuditEngine.unit_of_work()`, so the ADR-03 integrity check runs once, after the lock and recovery, before anything is staged. The export renders the whole file before it commits any entry, so a render that fails records nothing:

1. **Integrity check.** A project that fails it exits 2, and nothing is written.
2. **Gates.** Unless `--force` is given, a FAIL gate stops the export, and nothing is written.
3. **Stage `register.checkpoint`.** If the chain records no fingerprint for the system, or the fingerprint of the register as the current model serialises it differs from the latest one the chain records, the engine stages the register in that form and builds, without appending, a `register.checkpoint` entry with payload `{"riskforge_version": ...}` and the fingerprint of the staged result. Any `register.baselined` entries ADR-03 section 6 requires are built with it. This happens for a register last written by 1.1.3 or by an older model. If the staged register still does not match the serialised form, because a value does not survive the YAML round trip (ADR-03 section 3), the export stops, and the unit of work discards the staged register. The checkpoint records a rewrite that changes no value.
4. **Build.** The engine builds the content and its digest, then the chain proof (every committed entry, followed by the staged entries of step 3), the receipt for the last entry of the chain proof, the RMF signature when a signer is given, and `public_keys`. The document must validate against schema 1.1.0.
5. **Render and stage the file.** The exporter renders the whole file in memory. Its bytes are written to a temporary file in the target directory, created exclusively under a unique name (as `mkstemp` does) with mode 600 from the start, and flushed to disk. Temporary files carry a fixed RiskForge prefix, and the next export to a directory removes any it finds there that are older than the project lock it holds, so an interrupted export leaves no stale file holding a receipt for an entry that was never committed.
6. **Commit the checkpoint.** The staged entries of step 3 are appended exactly as built, with the staged register, and nothing else. The lock is held throughout, so no other entry comes between them and the chain proof. Every backend must make these entries and the writes staged with them durable before this step returns. The file store does, through its journal, the fsync of the log, the renames and the head file. A backend that commits only at the end of the outermost unit of work, as the `StorageBackend.unit_of_work` docstring allows, must offer a commit at this point inside the export's unit of work, or it cannot run exports. The `StorageBackend` docstrings state this contract.
7. **Rename.** The temporary file is renamed over the target, and the directory is flushed.
8. **`rmf.exported`.** Recorded only after the rename, with payload `{"export_id", "format", "sha256", "file_sha256"}`. `sha256` is the content digest. `file_sha256` is the SHA-256 of the bytes written, so a file of any format can be matched to its entry by hashing it.

A failure before step 6 (a render that fails, a schema violation, a missing or unwritable directory, a full disk) removes the temporary file and ends the unit of work with the error, which discards the staged register and entries. It leaves no file and records no entry, including no checkpoint. A failure inside step 6 also removes the temporary file, which is never renamed; whether the staged entries survive is then up to the backend's recovery, and no file names them. A failure after step 6 and before step 8 leaves a committed checkpoint, which changes no value, and possibly a renamed file with no `rmf.exported` entry; that file still verifies on its own. When no checkpoint is needed, steps 3 and 6 do nothing.

`register.checkpoint` is a new event. Like every `register.*` event, the integrity check treats it as one that changes a register. Adding `file_sha256` to the `rmf.exported` payload adds a key to an event 1.1.3 already writes. ADR-03 is not edited. This ADR records both changes.

### 8. Timestamps

Founder decision, 2026-10-12: the times that belong to the act of exporting live only in blocks the content digest leaves out. These are `generated_at`, `signed_at` in each RMF signature, `issued_at` in the receipt, and the `timestamp` of each chain proof entry. So two exports of one register state share a digest and can be compared by it.

The digest still covers the times that are part of the state being exported: the dates in the register, and `totp_verified_at` and `signed_at` inside each sign-off. A sign-off is fixed once made, so these do not change from one export to the next.

AGENTS.md hard rule 2 lists `id`, `generated_at` and, from schema 1.1.0, the fields this ADR defines in the provenance blocks as the known exceptions to reproducible export content. Because each provenance object forbids extra properties (section 1), no other field can join them without a new ADR.

### 9. Compatibility

- A 1.0.0 file written by 1.1.3 validates against `rmf-1.0.0.schema.json` and verifies under 2.0 with the 1.1.3 rule. `tests/fixtures/v1_1_3_project/rmf.json` is the reference. Its detached GPG signature, if any, is not checked by RiskForge, as before.
- Plain `verify --file` on a 1.0.0 file reports that only the content digest was checked and names the version. With `--trusted-key` or `--receipt`, a 1.0.0 file fails with exit code 2 (section 6), because it cannot carry a signature, a chain proof or a receipt.
- The 1.0.0 schema's content does not change. Its `$id` moves from `https://schemas.aiexponent.com/riskforge/rmf/v1.0.0`, which does not resolve, to its published URL. No digest depends on the schema's `$id`.
- RiskForge 2.0 writes only 1.1.0 files. RiskForge 1.1.3 hashes every key of a 1.1.0 file except its three blanked ones, so its `verify --file` reports a 1.1.0 file as tampered. Downgrade is not supported, as in ADR-03.
- `export --sign` changes meaning from a GPG key id to a key file path. Scripts that pass a GPG id exit 3 with a message, and no file is written.
- Audit chains, register fingerprints and the head file do not change. Audit entry signatures use the fields and the message ADR-03 already fixed. For 1.1.0 files this ADR supersedes ADR-03 section 7 bullets 1 to 3, as Context records.

## Rationale

- **Leaving the provenance blocks out of the digest** gives one digest for one register state, whatever the format and however often it is exported. Each block either verifies itself (signatures, receipt, chain proof) or describes the act of exporting (id, times). Hashing them would make every export unique and would make the signature circular, since the signature, receipt and chain proof are computed after the digest.
- **Recording `rmf.exported` after the write** means the log never names a file that was not written. The price is that the file cannot carry its own export entry's hash, so `audit_entry_hash` goes. The chain proof and receipt carry the chain head instead.
- **Rendering before the checkpoint commits** means a render failure leaves the project as it was. The chain proof can be built from staged entries because the lock is held and the entries are appended exactly as built.
- **Tying the receipt to the last chain proof entry** leaves no part of the chain proof outside the receipt's signature.
- **Refusing 1.0.0 under `--trusted-key` and `--receipt`** stops a file from escaping the trust check by declaring the older version.
- **Rejecting duplicate keys and non-finite numbers** keeps every JSON parser reading the same values from a file RiskForge verified.
- **Ed25519 with local key files** works offline, has no external binary or keyring state, behaves the same on every platform CI runs, and embeds the signature in the file, so it cannot be separated from it.
- **Comparing raw public key bytes** keeps trust independent of the 64-bit key id, which someone could deliberately collide, and of base64 spellings that decode to the same key.
- **Domain prefixes** stop a signature over one kind of record from verifying as another kind.
- **Receipts** are the record kept outside the project that ADR-03 said was missing. They need no server and no network.
- **The checkpoint** makes the chain proof end at the exact state the file holds, including for registers written before 2.0.

## Alternatives Considered

- **Keep the 1.1.3 rule for 1.1.0.** Every export would get its own digest, the three formats could not share one, and a signature over the digest could not cover a receipt or chain proof computed after it.
- **Put `signed_at` inside the digest.** It would date the content, but two exports of one register would no longer share a digest. Rejected by the founder decision of 2026-10-12. The signing time stays in the signature block.
- **Keep recording `rmf.exported` before the write.** That keeps `audit_entry_hash`, but a failed write leaves an entry for a file that does not exist, the defect this ADR fixes.
- **Commit the checkpoint before rendering.** Simpler, but a render that fails would leave a checkpoint in the log for an export that never happened.
- **Let the receipt name any chain proof entry.** Entries after it would be covered by no signature, and could be replaced and relinked.
- **Keep GPG.** It needs an external binary and keyring state that tests cannot reproduce offline, and its detached `.asc` file is easily separated from the export. RiskForge never checked it.
- **Sign the file bytes.** The PDF and Markdown bytes differ from the JSON bytes, so each format would need its own signature, and an embedded signature cannot cover the bytes that hold it.
- **RFC 8785 (JCS) for the digest.** That would add a second canonical form next to the one ADR-03 fixed for the audit chain. One form for every hash RiskForge computes is easier to check.
- **PyNaCl instead of `cryptography`.** It would add libsodium for no gain.
- **Anchor the chain head in a public transparency log.** That needs a network call, which AGENTS.md hard rule 1 forbids in the free CLI. RiskForge Team may offer it as an opt-in.
- **A chain proof of one system's entries only.** The chain is one per project, so a subset cannot be checked link by link.

## Trade-offs Accepted

- The content digest proves only that the content is consistent with itself. Without `--trusted-key`, a valid signature proves only that whoever holds the embedded key signed. The verifier has to get the signer's public key by some other route.
- Plain `verify --file` on a 1.0.0 file proves only self-consistency, and a 1.1.0 file rewritten as 1.0.0 passes it. Only `--trusted-key` or `--receipt` refuses such a file, so a relying party has to use one of them.
- Private keys are stored unencrypted, protected only by file mode. The mode check applies on POSIX systems only. There is no revocation. Rotation works because entries name their `key_id`, but PR 3 does not test it.
- `signed_at` and `issued_at` come from the local clock, and nothing checks them.
- With `--trusted-key`, a signed chain proof entry must verify but its key need not be trusted. The trusted receipt is what binds the chain proof.
- The chain proof holds the whole project log, so an export shows the audit entries of every system in the project, with actor identities and payloads, and grows with the log.
- Only the JSON export can be checked with `verify --file`. A PDF or Markdown file is checked by comparing the digest it shows with a verified JSON export of the same state, or by hashing it and comparing with `file_sha256` in the log.
- The whole rendered file is held in memory before it is written.
- If the rename fails after the checkpoint committed, or the process stops between the two, the checkpoint stays in the log with no file, and after a stop a temporary file may stay in the target directory. The checkpoint records a rewrite that changes no value.
- If the process stops between the rename and the `rmf.exported` entry, a file exists with no entry for it. The file still verifies alone, since its chain proof ends before the export.
- A receipt proves only the entries up to its `seq`. `verify --receipt` does not compare a receipt's `register_fingerprint` with the project's current register, which may have changed since, for good reasons.
- As in ADR-03, a receipt or sign-off edited in a way that leaves every field value the same after parsing (for example `+00:00` in place of `Z`) is not detected, and does not change what it records.
- A document that declares an unknown `rmf_schema_version` exits 3, not 2.
- Canonical JSON follows Python's `json.dumps`, not a published standard.

## Enforcement

PR 3 adds these tests:

- `tests/unit/test_signing.py` and `tests/integration/test_keygen.py`: keys, key ids, signatures, mode 600, no overwrite, strict base64 and length checks.
- `tests/unit/test_receipts.py` and `tests/integration/test_receipt_command.py`: a receipt catches a log cut back with the head file rewritten, which plain `verify` passes; edited, untrusted and unsigned receipts; signed audit entries; a receipt file with a duplicate key.
- `tests/contract/test_rmf_schemas.py`: both schemas and their `$id` values, the 1.1.3 file still validating and matching its digest, 1.1.0 rejecting `signed_by` and `audit_entry_hash`, an extra property in each provenance object rejected, the digest ignoring each left-out field and covering the content and sign-offs.
- `tests/integration/test_export_command.py`: one digest across JSON, PDF and Markdown; `rmf.exported` after the write, with `file_sha256`; a forced render failure, a schema violation and an unwritable path each leaving no file and no new entry, including on a project that needs a checkpoint, whose register stays byte for byte unchanged; the embedded receipt naming the last chain proof entry; the committed checkpoint entries byte-identical to the end of the chain proof; a stale temporary file from an interrupted export removed by the next export to that directory; signed exports; a GPG key id refused; a 1.1.3 project exporting with a checkpoint.
- `tests/integration/test_verify_file.py`: untouched 1.0.0 and 1.1.0 files pass; edits to the register, chain proof, receipt, a signature, a sign-off or the retired fields fail with exit code 2; an entry appended after the receipt's `seq`, an empty chain proof and a chain proof with no fingerprint for the system fail; a 1.1.0 file rewritten as 1.0.0 fails with `--trusted-key` and with `--receipt` and passes plain `verify --file` with the digest-only message; duplicate keys at the top level and inside the register, `NaN`, and a number such as `1e400` that is not finite as a float, fail; duplicate key ids, a key id with no record, a wrong algorithm and a receipt `public_key` that differs from its record fail; a sign-off from an untrusted key fails with `--trusted-key`; `--trusted-key` and `--receipt` with `--file`.
- `tests/integration/test_v113_compat.py`: the 1.1.3 fixture still verifies.

## Consequence

Any later change to the content digest, to the fields it leaves out, to the fields of `signatures[]`, `public_keys[]`, `signoffs[]`, `chain_proof` and its entries, or the receipt, to a signing message or its domain prefix, to the `key_id` rule, to key resolution or to the rules for reading RMF and receipt files needs a new ADR, and a new RMF schema version or prefix version for the records it changes. Files written under 1.0.0 and 1.1.0 must keep verifying with the rules above. A storage backend other than the file store must make appended entries durable inside the export's unit of work (section 7 step 6), or it cannot run exports.
