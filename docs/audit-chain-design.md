# Audit Chain Design

> How RiskForge records every change to a project, how `riskforge verify` checks the
> record, and what that check can and cannot prove. Source of truth:
> `src/riskforge/integrity/` (hashing, signing, RMF checks), `src/riskforge/engine/integrity.py`
> (the project check) and `src/riskforge/storage/filesystem.py` (how files are written).
> The decisions behind this design are recorded in
> [ADR-03](adr/ADR-03-register-fingerprints-and-integrity-check.md) and
> [ADR-04](adr/ADR-04-rmf-content-digest-and-signatures.md).
>
> Audience: security architects, engineers, and the technical reviewers of a
> conformity assessment. Read this before relying on a RiskForge project as evidence.

---

## 1. Why an audit chain

Article 9(1) of the EU AI Act requires that a risk management system "shall be
established, implemented, documented and maintained", and Annex IV point 5 asks for "A
detailed description of the risk management system in accordance with Article 9". A
reviewer looking at that documentation needs to know that the risk register in front of
them is the one the assessment produced, who changed it, and when.

RiskForge answers this with a hash chain. Every change appends one entry to
`.riskforge/audit.jsonl`; each entry carries the SHA-256 hash of the entry before it and a
fingerprint of the register after the change. Changing any entry breaks every hash after
it, and changing a register without RiskForge breaks the link between the register and
the last entry that describes it. A reviewer needs the files and the published algorithm,
nothing else.

The audit chain records the risk management process. It is not the automatic recording
of events (logs) that Article 12(1) requires a high-risk AI system to allow; those logs
belong to the AI system, not to RiskForge.

---

## 2. Design

### 2.1 Files

```
.riskforge/
├── audit.jsonl        one JSON entry per line, append-only (mode 600)
├── audit.head.json    {"seq": ..., "entry_hash": ...} of the last entry RiskForge wrote
├── audit.lock         serializes writers across processes
├── txn.json           exists only while a change is being committed
└── systems/<system-id>/system.yaml, register.yaml, mitigations.yaml
```

An entry, formatted for reading (on disk it is one line, and the hashes are 64 hex
characters):

```json
{
  "seq": 3,
  "event": "risk_item.created",
  "timestamp": "2026-10-17T19:30:17.912345Z",
  "actor": {"type": "human", "identity": "Alice Chen"},
  "system_id": "4a3cbcd1-0841-46e6-af5a-6f37af068f28",
  "payload": {"risk_item_id": "646bec44-...", "dimension": "discrimination", "score": 20},
  "prev_hash": "dace...18dd",
  "entry_hash": "9c4f...a7d0",
  "register_fingerprint": "e3b0...b855"
}
```

- `seq` counts from 0 with no gaps. The first entry's `prev_hash` is `"0000000000"`.
- `actor.identity` is what the user typed (`--assessor-name` or `--by`, for example). The
  CLI does not authenticate it.
- `register_fingerprint` is the SHA-256 of the canonical JSON (section 2.3) of the
  system's stored `register.yaml` after the change, read back with `yaml.safe_load`.
  Entries written by RiskForge 1.1 do not have it, and neither do entries written
  before the system has a register, such as `system.created`.
- `key_id` and `signature` appear only on entries signed by a program that gives
  `AuditEngine` a signing key (section 2.6). The CLI does not sign entries.

### 2.2 One change, one entry, together

Before a command changes or exports anything, it runs the integrity check (section 2.4)
and stops with exit code 2 if the check fails. The change itself then runs inside
`StorageBackend.unit_of_work()`, which for the file backend:

1. takes the lock (`audit.lock`) and finishes or discards any change a crash left behind;
2. writes each changed file next to its target as `<name>.pending`;
3. writes `txn.json`, which lists the pending files and the length of the log;
4. appends the audit entry and flushes it to disk;
5. renames each pending file into place, writes `audit.head.json`, and deletes `txn.json`.

If the process stops before step 4 finishes, the next command discards the pending files
and cuts off a partly written entry. If it stops after step 4, the next command finishes
the renames. Either way the register on disk is one the chain describes, so a mismatch
found later means someone changed the files outside RiskForge, not that a command
crashed. Four processes adding 25 risk items each to one register leave exactly 100
items and an intact chain (`tests/integration/test_concurrent_writers.py`).

### 2.3 Hashing

```python
import hashlib, json

def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")

def entry_hash(entry: dict) -> str:
    data = {k: v for k, v in entry.items() if k != "signature"}
    data["entry_hash"] = ""
    return hashlib.sha256(canonical_json(data)).hexdigest()
```

- `entry` is the line as stored, `prev_hash` included. Optional fields that are absent
  stay absent, so entries written by RiskForge 1.1 hash exactly as they did then.
- The signature is left out because it signs the hash.
- `sort_keys` and the compact separators make the bytes independent of formatting.
  Non-ASCII text is escaped (`ü` becomes `\u00fc`), as `json.dumps` does by default.

This is not RFC 8785 (JCS). A verifier written in another language must reproduce
Python's `json.dumps` output for these settings.

### 2.4 What `riskforge verify` checks

`riskforge verify` opens the project read-only and takes no lock, so it also works on a
read-only copy or an archive mount. It reports every finding, not only the first, and
exits 2 if any of these fail:

| Check | Catches |
| --- | --- |
| Each entry's `seq`, `prev_hash` and `entry_hash` | Edited, inserted, deleted or reordered entries |
| The last entry against `audit.head.json` | A log cut back to an earlier entry, or entries added outside RiskForge (unless the head file was rewritten too) |
| Each system's stored register against the latest `register_fingerprint` for that system | A register edited, replaced or deleted outside RiskForge |
| Each `system.yaml` against the copy of the system in its register | A system file edited outside RiskForge |
| A project with systems but no audit log, and systems named in the log against the files on disk | A deleted log or a deleted system directory |
| Entry signatures, when `--trusted-key` names the signing key | Entries forged without the key |
| `--receipt FILE` against the chain | A log cut back below the receipt's entry, or any entry up to and including it rewritten (section 2.5) |

Every command that changes or exports data runs the same check first, so nothing is
added on top of a project that was altered. A project last written by RiskForge 1.1 has
no fingerprints and no head file yet: `verify` passes with a warning, the next change or
export records them, and `verify --strict` exits 2 until then. A change in progress
(`txn.json` exists) makes `verify` retry briefly, then check the project as the next
command would recover it: exit 1 if that view is clean, exit 2 if it has a finding or
the journal is not one RiskForge wrote.

### 2.5 Receipts

A receipt is a small JSON file that names the `seq` and `entry_hash` of the last entry
of the audit log, and the latest register fingerprint the log records for one system:

```bash
riskforge receipt <system-id> --output ~/riskforge-receipts/loan-scoring.json
riskforge receipt <system-id> --output ~/riskforge-receipts/loan-scoring-signed.json --sign KEY
riskforge verify --receipt ~/riskforge-receipts/loan-scoring.json
```

Keep it where the project's editors cannot change it: with your client, your auditor, or
in a separate repository. `verify --receipt` exits 2 when the log no longer holds that
entry with that hash at that position, or when the receipt's fingerprint is not the last
one the log records for its system up to that entry. This is the check that catches
someone who rewrote the log and the head file with the public algorithm, for every
entry up to the one the receipt names (section 3.2). Entries written after the receipt
are not covered. Every JSON export also carries a receipt, so a saved export works as one:
`riskforge verify --receipt rmf.json`.

### 2.6 Signatures

`riskforge keygen --output KEY` creates an Ed25519 key pair: `KEY` (PKCS8 PEM, not
encrypted, mode 600 on Linux and macOS) and `KEY.pub`. A key is named by its `key_id`,
`ed25519:` followed by the first 16 hex characters of the SHA-256 of the raw public key;
trust always compares the full key. RiskForge refuses a private key file that other
users can read.

Each signature covers a fixed prefix plus the signed value, so a signature made for one
purpose cannot be reused for another:

| What is signed | Message |
| --- | --- |
| An export | `riskforge.rmf.v1\n` + the content digest |
| A receipt | `riskforge.receipt.v1\n` + the canonical JSON of the receipt without `public_key` and `signature` |
| An audit entry | `riskforge.audit-entry.v1\n` + the entry hash |
| An approver's sign-off | `riskforge.signoff.v1\n` + the canonical JSON of the sign-off without `signature` |

The JSON export embeds the public keys it was signed with. `verify --file` checks every
signature against them; `--trusted-key KEY.pub` also requires that the signer is a key
you expected. The audit log holds no public keys, so a signed audit entry is checked
only with `--trusted-key`.

### 2.7 What an export carries

A JSON export (RMF schema 1.1.0) carries a content digest (`sha256_hash`), the
signatures, the public keys, a chain proof (every entry of the audit log up to the
export) and a receipt for the last of those entries. The digest leaves out `id`,
`generated_at`, `sha256_hash` and those four provenance blocks, so the JSON, PDF and
Markdown exports of one register show the same digest. `riskforge verify --file`
checks the schema, recomputes the digest, checks every signature and sign-off, re-links
the chain proof, and checks that the proof's last fingerprint for the system matches the
register in the file. It needs only the file. The `rmf.exported` entry that records the
export is written after the file and stores the SHA-256 of the file's bytes
(`file_sha256`). If the export fails before the checkpoint, if any, is committed,
neither a file nor an entry is left. If the rename then fails, no file is written, but a
committed checkpoint entry stays. If it fails after the rename, while flushing the directory or
recording `rmf.exported`, the file stays without an `rmf.exported` entry; a failed flush
says the export was not recorded. A file written
by RiskForge 1.1 (RMF schema 1.0.0) gets the schema and digest check only.

---

## 3. Threat model

### 3.1 What RiskForge detects

| Threat | Detected by |
| --- | --- |
| Editing any audit entry (for example backdating an acceptance) | `verify`: hash mismatch from that entry on |
| Inserting, deleting or reordering entries | `verify`: sequence and `prev_hash` errors |
| Cutting the last entries off the log | `verify`: the log no longer reaches `audit.head.json` (unless `audit.head.json` is edited to match) |
| Editing a register (scores, acceptances, deleted items) | `verify`: fingerprint mismatch; every changing command refuses to run |
| Deleting the log or a system directory | `verify`: missing log or missing files |
| Rewriting entries up to a receipt's `seq`, head file included | `verify --receipt` with that receipt |
| Altering an exported file (content, signatures, sign-offs, chain proof, receipt) | `verify --file`, and with `--trusted-key` also a file re-signed with another key |
| Two writers at once on one machine | Prevented by the lock; no lost updates |
| A crash in the middle of a change | Finished or discarded by the next command |

### 3.2 What RiskForge does not detect

| Out-of-scope threat | Why | Where it is handled |
| --- | --- | --- |
| The assessment does not describe the deployed system | The chain shows what was recorded, not that it is true | Provider's quality management; independent review |
| The assessor was not competent, or an acceptance was unreasonable | Judgements are recorded, not graded | Competence controls; independent review |
| Someone with write access recomputes the entries from a change onward and the head file (cutting entries off the end needs only a matching head-file edit), and no receipt covers those entries | The algorithm is public and holds no secret, so a consistent rewrite verifies (ADR-03) | Take a receipt after each export or review and keep it outside the project; sign exports with a key the project's editors do not hold |
| A wrong clock | Timestamps come from the local clock; `seq` orders entries, not wall time | Trusted timestamping (not built) |
| A claimed identity is false | `actor.identity` is typed by the user in the CLI | A program that authenticates users and signs entries |
| Two git branches that both changed `.riskforge/` are merged | The merged log is no longer one chain, so `verify` exits 2; it cannot be repaired automatically | One writer per project; do not merge `.riskforge/` |
| A host that was compromised before any entry was written | Every entry is the attacker's | Host security |

The chain makes changes outside RiskForge detectable unless the person making them
recomputes the chain and the head file. Receipts kept outside the project extend
detection to every entry they cover. Neither makes an assessment correct or replaces
independent review.

---

## 4. Evidentiary value

Claims that hold up:

- "This is the recorded history of the assessment; `riskforge verify` passes on it." The
  reviewer can run the check on a read-only copy and reproduce the result.
- "This export is the register the chain recorded last, signed with this key." `verify
  --file --trusted-key` checks both.
- "The log still holds, unchanged, every entry up to the one in this receipt."
  `verify --receipt` checks it.

Claims that do not:

- "The audit chain shows the assessment is correct." It shows the files are consistent
  with each other and, for the entries a receipt covers, unchanged since the receipt.
- "The actor names are verified identities." In the CLI they are typed by the user.
- "This replaces independent attestation." It is one input to it.

---

## 5. Verification recipe

### 5.1 With RiskForge

In an isolated environment:

```bash
python -m venv .venv && . .venv/bin/activate
pip install riskforge
riskforge verify --project-dir submission/
riskforge verify --file submission/rmf.json --trusted-key provider-signing.pem.pub
riskforge verify --project-dir submission/ --receipt receipt-from-the-provider.json
```

Each command exits 0 when the check passes and 2 when it finds a problem.

### 5.2 Without RiskForge

The chain, the head file and the register fingerprints can be checked with Python and
PyYAML only:

```python
import hashlib, json
from pathlib import Path

import yaml

root = Path("submission/.riskforge")

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")

prev = "0000000000"
latest = {}
lines = (root / "audit.jsonl").read_text(encoding="utf-8").splitlines()
for seq, line in enumerate(lines):
    entry = json.loads(line)
    data = {k: v for k, v in entry.items() if k != "signature"}
    data["entry_hash"] = ""
    assert entry["seq"] == seq, f"sequence gap at line {seq}"
    assert entry["prev_hash"] == prev, f"broken link at seq {seq}"
    assert hashlib.sha256(canonical(data)).hexdigest() == entry["entry_hash"], f"hash mismatch at seq {seq}"
    if entry.get("register_fingerprint"):
        latest[entry["system_id"]] = entry["register_fingerprint"]
    prev = entry["entry_hash"]

head_file = root / "audit.head.json"  # absent in a project last written by RiskForge 1.1
if head_file.exists():
    head = json.loads(head_file.read_text(encoding="utf-8"))
    assert head == {"seq": len(lines) - 1, "entry_hash": prev}, "the log does not end at the head file"
for system_id, fingerprint in latest.items():
    register = yaml.safe_load((root / "systems" / system_id / "register.yaml").read_text(encoding="utf-8"))
    assert hashlib.sha256(canonical(register)).hexdigest() == fingerprint, f"register of {system_id} was changed"
print(f"Verified {len(lines)} entries and {len(latest)} register(s).")
```

If this script and `riskforge verify` agree, the result does not depend on trusting the
RiskForge package. The script does not check `system.yaml`, signatures or receipts;
`riskforge verify` does.

### 5.3 Questions the check cannot answer

- Is the assessor plausible for this provider?
- Are the timestamps paced like real work? Eighty entries in ninety seconds came from a
  script, even if the chain verifies.
- Does the `system_id` match the AI system under review?
- Are the changes you would expect present, for example a reassessment after a major
  model change?

These are questions for the provider, not for an algorithm.

---

## 6. Limits that remain

- No trusted timestamps: time order comes from `seq` and the local clock.
- No public anchoring: a receipt held by someone outside the project is the outside copy.
- The CLI does not authenticate users or sign audit entries. A program that uses the
  engine from Python can give `AuditEngine` a signing key and an authenticated identity;
  `verify --trusted-key` then checks those signatures, and `export --public-key` embeds
  their public keys in the export's `public_keys` block.
- Concurrent writers are serialized on one machine. A project on a network file system,
  or copied between machines and changed on both, can fork; `verify` then exits 2.

---

## 7. Summary

- One JSON line per change, SHA-256 linked, with a fingerprint of the register after the
  change. Genesis `prev_hash`: `"0000000000"`. Chains written by RiskForge 1.1 still verify.
- A change and its entry are committed together under a lock; a crash is finished or
  rolled back by the next command.
- `riskforge verify` exits 0 when intact and 2 on any finding, and every changing command
  runs the same check first.
- Receipts kept outside the project catch a rewrite of any entry up to the receipt.
  Ed25519 signatures bind exports, receipts and sign-offs to a key.
- The chain shows the files are consistent and, with a receipt, that the history up to
  the receipt is unchanged. It does not show the assessment is right.

If this document and the code disagree, the code wins and this document needs a fix. File
an issue at <https://github.com/aiexponent/riskforge/issues>.
