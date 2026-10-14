# ADR-03: Register Fingerprints in the Audit Chain and One Integrity Check

**Status:** Proposed (accepted when the maintainer merges the 2.0.0 integrity change, PRD-320)
**Date:** October 2026
**Deciders:** Maintainer

## Context

Up to 1.1.3 the audit chain hashes only its own entries. Nothing ties an entry to the register it produced, nothing records where the log should end, and an empty or missing log counts as valid. As a result `riskforge verify` exits 0 after a register is edited by hand, after the last entries of `audit.jsonl` are cut off, after the log is deleted, and after the whole chain is rebuilt (PRD-332). Commands that change data also write new entries on top of a chain that is already corrupt (PRD-333).

AGENTS.md hard rule 5 says any change to the audit chain hash needs an ADR before the code. This ADR is that record. It adds fields to what an entry hash covers, adds a head file, and defines the one check that `verify` and every changing command run. It keeps every hash written by 1.1.3 valid.

## Decision

### 1. Three optional entry fields

`AuditEntry` gains three optional fields, all absent by default:

| Field | Meaning | Covered by `entry_hash` |
| --- | --- | --- |
| `register_fingerprint` | SHA-256 of the system's register as stored after the change (section 3) | Yes |
| `key_id` | Identifier of the key that signed the entry | Yes |
| `signature` | Signature over the entry hash | No, it signs the hash |

When `register_fingerprint`, `key_id` or `signature` is `None`, that key is left out of the stored line and out of the hashed data, and is never written as `null`. Every other key, including `null` values inside `payload`, is stored and hashed as is, as in 1.1.3.

No command signs entries in this change. The `key_id` and `signature` rules are fixed here so a later signer does not change how entries hash. Once signatures are verified, an entry that has `key_id` and no `signature` fails the check.

### 2. Entry hash rule

```python
def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")

def entry_hash(entry: dict) -> str:
    # entry["prev_hash"] is hashed as stored; the chain check separately requires it
    # to equal the previous entry's entry_hash ("0000000000" for seq 0).
    data = {k: v for k, v in entry.items() if k != "signature"}
    data["entry_hash"] = ""
    return sha256(canonical_json(data)).hexdigest()
```

- `entry` is the entry as RiskForge reads it: the stored line validated as an `AuditEntry` and dumped back with `model_dump(mode="json")`, with absent optional fields left out. 1.1.3 hashed the same dump and stored the same dump, so every line 1.1.3 wrote hashes to its stored value.
- The algorithm, the key order, the separators and the ASCII escaping of non-ASCII text are the ones 1.1.3 uses. Only the set of fields that can appear grows.
- Because the entry is read through the model, an edit that does not change any field value after parsing (an unknown extra key, `+00:00` in place of `Z`, `"0"` in place of `0`) is not detected. Such an edit does not change what the entry records.
- A signature, when one is added later, signs the bytes `b"riskforge.audit-entry.v1\n"` followed by the hex entry hash.
- This is not RFC 8785 (JCS). A verifier in another language must reproduce Python's `json.dumps` output for these settings.

### 3. Register fingerprint

`register_fingerprint = SHA-256(canonical_json(document))`, where `document` is the result of `yaml.safe_load` (PyYAML `SafeLoader` or `CSafeLoader`, YAML 1.1 resolution) applied to the bytes of `register.yaml`, not a model serialised again. The writer computes it by parsing the exact YAML text it writes, not from the dictionary it dumped, because some strings do not survive a YAML round trip (U+0085 reads back as a space). A later release that adds a model field therefore does not see an old register as changed, and a later release must not change the loader without a new ADR.

If `register.yaml` does not parse, or parses to a value `canonical_json` cannot encode (a YAML date, timestamp, `!!binary` or `!!set` value, or a mapping with keys of mixed types), the check reports the register as not matching its fingerprint. It does not raise.

Every entry written for a system that has a register carries the fingerprint of that register after the change. Every register write, including the first one `assess` makes, records an entry in the same storage unit of work (PRD-331). No command writes a register without one. A crash during a change therefore does not by itself leave a register that fails to match the latest fingerprint. A mismatch means the register changed after RiskForge wrote it, whether by a person, another tool, a restored backup or disk damage. The check cannot tell which.

### 4. Head file and unit of work

`.riskforge/audit.head.json` holds `{"seq": ..., "entry_hash": ...}` of the last entry RiskForge wrote. It is written in the same unit of work as the entry. It is not part of any hash.

`init` records a `system.created` entry for the system it creates, so a 2.0 project always has a log once it has a system.

A unit of work writes its journal, `.riskforge/txn.json`, before it touches the register, the system file, the log or the head file, and removes the journal last. The journal holds `after_seq`, `log_size` (the length of the log before the append), `count` (how many lines the append writes, 1 when absent) and `files` (the staged system files, each `systems/<id>/system.yaml`, `register.yaml` or `mitigations.yaml`). One change may append several chained entries (its own and the `register.baselined` entries of section 6): all their lines go to the log in one write and one fsync, and the head file then names the last of them. Recovery keeps the append only when exactly `count` complete lines hold the entries `after_seq + 1` to `after_seq + count`, every one after the first being `register.baselined`; fewer such lines followed by nothing or by a cut-off line are cut back to `log_size`, and anything else is left as it is and reported. A journal that does not have this shape, has a `count` above 10,000, names any other file, or does not fit the log (a `log_size` beyond its end or not at the end of a line, or an `after_seq` that is not the seq of the entry ending at `log_size`, or not -1 when `log_size` is 0) was not written by RiskForge for this log: recovery stops with an integrity failure and touches nothing.

A changing command takes the audit lock, completes or rolls back any unfinished change the journal records, and only then runs the integrity check.

### 5. One integrity check

`check_integrity()` in `riskforge.engine.integrity` is the only verification path. `riskforge verify` runs it, and every command that changes or exports data runs it first and stops with exit code 2 when it fails (PRD-333). The engine enforces the same rule: `AuditEngine` opens every change through `checked_unit_of_work()`, which runs the check once per outermost unit of work, after the lock and recovery and before anything is staged, and raises `IntegrityError` when it fails. So nothing is appended to a project that fails the check, and no `register.baselined` entry is recorded unless the check passed. The check reports every finding, not only the first. It fails on the rows below. Each row catches its change only when the other files were not rewritten to agree with it (see Trade-offs Accepted).

| Check | Catches |
| --- | --- |
| Each entry's `seq`, `prev_hash` and `entry_hash`; every line is exactly one UTF-8 JSON entry ended by `\n` (no byte order mark, carriage return or surrounding white space), and the log ends with `\n`. A line may end with `\r\n` instead, as 1.1.3 wrote on Windows; a carriage return anywhere else fails. A log that cannot be read is itself a failure | Edited, inserted, deleted, reordered or garbled entries, and bytes that make readers disagree on the lines |
| `audit.head.json` parses, and its `seq` and `entry_hash` equal those of the last entry in the log | A log cut back to an earlier entry, or entries appended outside RiskForge |
| A missing head file while the log holds entries with fingerprints, or any event only 2.0 writes (`system.created`, `register.created`, `register.baselined`) | A head file deleted to hide a cut |
| Each system's stored register against the latest `register_fingerprint` for that system | A register edited or replaced outside RiskForge |
| Once a head file exists, a register with no fingerprint in the log | A register added or swapped in by hand |
| A system whose log holds register events (`register.*`, `risk_item.*`, `mitigation.*`, `risk.accepted`) but has no `register.yaml` | A deleted register, including one last written by 1.1.3 |
| A project with systems but an audit log that is missing or holds no entries | A deleted or emptied log |
| Systems named in the log against the files on disk | A deleted system directory |
| Once a head file exists, any directory under `systems/` that no entry names, whatever it holds; a named directory without `system.yaml`; a directory name that is not a valid system id | A system added by hand, or a system file deleted |
| Each `system.yaml` parses, validates as `AISystem`, has an `id` equal to its directory name, and, when the system has a register, equals the `system` mapping of the parsed register document | A corrupt or hand-edited system file |

The check reads a stored file (register, system file, journal, head file, log) only when it is a regular file of at most 64 MiB (1 GiB for `audit.jsonl`), opened without blocking and checked through its descriptor, so a directory, FIFO, device or symlink to one is refused without being read. A file that is not one, is larger, cannot be read or nests too deeply to parse is a finding for that file, never a crash or a hang.

`verify` opens the project read-only: it takes no lock and writes no file, so it works on a read-only copy or an archive mount. A `txn.json` that is not a journal RiskForge wrote (see section 4) is a failure at once. Otherwise it reads `txn.json` and `audit.head.json` before and after the check. If either changed, or `txn.json` is present, it repeats the check up to three times. If a journal is still present after that, it checks, without writing, the project as recovery would leave it. When recovery would cut the append off, that is the log up to `log_size` with the committed files and the stored head. When recovery would keep it, that is the whole log with each staged `.pending` file in place of its committed file and the last appended entry as the head, and the stored head must be the one before the change or the one after it. A journal recovery would refuse is a failure. `verify` exits 2 if that check fails. Otherwise it reports that a change is in progress or unfinished and exits 1, not 2, so a write that overlaps `verify` is not reported as tampering, and a planted journal cannot hide tampering anywhere.

### 6. Compatibility with 1.1.3

- Entries written by 1.1.3 have none of the new fields, so their canonical JSON, and therefore their hash, is byte for byte what 1.1.3 computed. The 1.1.3 fixture in `tests/fixtures/v1_1_3_project/` verifies under the new code.
- A log that holds only 1.1.3 entries has no head file, and passes. The head file appears with the next entry.
- A register with no fingerprint in the log (last written by 1.1.3) passes with a warning only while the project has no head file. The first changing command 2.0 runs in such a project, after the check passes, records one `register.baselined` entry for each other system on disk, carrying the fingerprint of its register when it has one, in the same unit of work as its own change. From then on a register with no fingerprint fails. A 1.1.3 register edited by hand before the upgrade is baselined as found.
- A 1.1.3 project with a system but no log entries (only `init` ran, or `assess` wrote an empty register and stopped) has no head file. When every register in it holds no items, the check passes with a warning and the next change records the baseline. Otherwise the check fails, because nothing distinguishes it from a deleted log, and the message names the files involved.
- A project in which an older release updated `system.yaml` without the copy in its register fails the `system.yaml` row. The message names both values.
- Downgrade is not supported. RiskForge 1.1.3 drops the new fields when it recomputes a hash and reports a 2.0 chain as corrupt.

### 7. What does not change

- The SHA-256 of an exported Risk Management File and the fields blanked before that hash (`sha256_hash`, `audit_entry_hash`, `signed_by`).
- `riskforge verify --file` behaviour.
- The audit event names and payloads that 1.1.3 already writes. 2.0 adds events (`system.created`, `register.created`, `register.baselined`) and does not change existing ones.

## Rationale

- **Fingerprints close the gap between log and data.** The chain already makes edits to the log detectable unless every later entry is recomputed too. Recording the register's hash in each entry extends that to the register itself, at the cost of one SHA-256 over the register per change.
- **Optional, absent-when-empty fields keep old hashes valid.** Re-hashing or migrating old chains would break the evidence trail of every existing project. Leaving absent fields out of the hashed data makes the new rule a superset of the old one.
- **Hashing the stored document, not the model,** keeps fingerprints stable across releases that add model fields.
- **One check for `verify` and the pre-flight** means no RiskForge command from 2.0 on writes to a project that `verify` rejects, and the two cannot drift apart.

## Trade-offs Accepted

- The checks catch changes that leave the files disagreeing with each other. Anyone with write access to `.riskforge/` can make a change pass using the public algorithm. Cutting entries off the end needs only a matching edit to `audit.head.json`. Editing a register needs only the entries from that change onward, and the head file, recomputed. Nothing here proves who made a change, when it was made, or that the log is complete. Only a record kept outside the project, such as a receipt or a signed export held by someone else, can catch such a rewrite. This ADR does not add one.
- Someone who cuts the log back to its last 1.1.3 entry and deletes the head file gets only warnings, because no fingerprinted entry remains to require the head file.
- Hand edits to `system.yaml` made before the system has a register are not detected. The register copies the system when it is created.
- `mitigations.yaml` and `riskforge.yaml` are not covered by any fingerprint.
- `actor.identity` and `timestamp` record what the local environment reports. The hash covers them, but nothing checks them, so they show what was recorded, not who acted or when. `seq` orders entries, not timestamps.
- Canonical JSON follows Python's `json.dumps`, not a published standard.

## Enforcement

- `tests/unit/test_entry_hashing.py`: entries without the new fields hash as in 1.1.3, including a 1.1.3-style entry with a `null` payload value; entries with them carry and cover the fingerprint.
- `tests/integration/test_v113_compat.py`: the 1.1.3 fixture still verifies.
- `tests/unit/test_integrity_check.py` and `tests/integration/test_verify_command.py`: each row of the table in section 5, the baseline rule, the read-only mode, a check run while `txn.json` is present, and a register hand-edited to an unquoted date, `!!binary`, `!!set` or mixed key types, or containing U+0085.
- `tests/integration/test_tamper_probes.py`: every changing command refuses a tampered project with exit code 2 and leaves it byte for byte unchanged.

## Consequence

Any later change to what an entry hash covers, to the fingerprint rule, to the YAML loader or to the head file needs a new ADR. A storage backend other than the file store must store entries with absent optional fields left out and must return the register document as stored, or fingerprints will not match.
