# RiskForge user guide

RiskForge is an open-source command-line tool that turns EU AI Act Article 9 risk
management into a developer workflow. You run a guided assessment across 8 risk
dimensions, score and treat each risk, and export a tamper-evident **Risk
Management File** (RMF) shaped for an Annex IV technical documentation pack.

RiskForge is not legal advice and not a notified-body conformity assessment. Every
export carries a disclosure to that effect that RiskForge always includes and no option
removes; it is part of the content digest.

---

## Contents

1. [Install](#install)
2. [Core concepts](#core-concepts)
3. [Quickstart: a worked example](#quickstart-a-worked-example)
4. [Non-interactive assessment](#non-interactive-assessment)
5. [Command reference](#command-reference)
6. [Exit codes (for CI)](#exit-codes-for-ci)
7. [Continuous integration recipe](#continuous-integration-recipe)
8. [Interpreting the RMF](#interpreting-the-rmf)
9. [Extending RiskForge (plugins)](#extending-riskforge-plugins)
10. [Limitations and disclosure](#limitations-and-disclosure)
11. [FAQ](#faq)

---

## Install

```bash
pip install riskforge
```

RiskForge requires Python 3.11, 3.12 or 3.13. JSON and Markdown export need nothing
beyond the `pip install`. **PDF export** additionally needs the Pango, cairo, and
GDK-PixBuf system libraries (used by WeasyPrint):

- Debian/Ubuntu: `sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info`
- macOS: `brew install pango cairo gdk-pixbuf libffi`
- Windows: WSL2 (Ubuntu) recommended with the Debian/Ubuntu packages above, or GTK3 runtime for native Windows

RiskForge makes zero outbound network calls in CLI mode. This is enforced in the
test suite with `pytest-socket`.

---

## Core concepts

- **System.** The high-risk AI system you are assessing. You register it with
  `riskforge init` and it gets a UUID (the *system id*) used by every later command.
- **Register.** The living record of risk items for a system.
- **Risk item.** One identified risk in one of the 8 dimensions, scored on a 5x5
  likelihood-by-severity matrix (`risk_score = likelihood x severity`, range 1 to 25).
  Bands: low (1 to 4), medium (5 to 9), high (10 to 16), critical (17 to 25).
- **Mitigation.** A control recorded against a risk item, after which you re-score
  the residual likelihood and severity.
- **Validation gates.** Eight readiness checks (G1 to G8) run before export.
- **Risk Management File (RMF).** The export artefact, in JSON, PDF, or Markdown,
  carrying a SHA-256 self-verifying digest and a link to the audit chain.
- **Audit chain.** Every state change is written to an append-only, SHA-256
  hash-chained log together with a fingerprint of the register it produced, so an
  edit to the log or to the register is detectable with `riskforge verify`, unless
  the editor also recomputes the chain and the head file (see Receipts).
- **Signing key and receipt.** `riskforge keygen` creates an Ed25519 key that signs
  JSON exports and receipts. A receipt names the last audit entry; kept outside the
  project, it shows later that the log up to that entry was not cut back or rewritten.

The 8 dimensions and their shipped question counts (37 total): health_safety (6),
privacy (5), robustness (5), data_governance (5), discrimination (4),
fundamental_rights (4), human_oversight (4), transparency (4).

---

## Quickstart: a worked example

An AI CV-screening system for hiring (an Annex III employment use case).

```bash
# 1. Register the system (prints the system id)
riskforge init \
  --name "TalentScreen CV Ranker" \
  --sys-version "3.2.0" \
  --purpose "Automated resume screening and candidate ranking for hiring." \
  --provider "Northwind HR Technologies GmbH" \
  --category employment

# 2. Record your Article 6(2) Annex III self-classification (clears gate G2)
riskforge system classify <system-id> --confirm

# 3. Run the guided 8-dimension assessment
riskforge assess <system-id> \
  --assessor-name "Dr. Lena Fischer" \
  --assessor-role "AI Governance Lead"

# 4. Record a mitigation and accept residual risk (optional but expected for high risks)
riskforge risk list <system-id>
riskforge risk mitigate <system-id> <risk-id> \
  -m "Remove postcode feature; add demographic parity monitoring" \
  -c preventive --owner "ML Platform" --residual-likelihood 2 --residual-severity 3 \
  --by "Dr. Lena Fischer, AI Governance Lead"
riskforge risk accept <system-id> <risk-id> --rationale "Residual within appetite after controls." \
  --by "Dr. Lena Fischer, AI Governance Lead"

# 5. Save test requirements for knowledge-gap risks and risks scoring 9 or more (clears gate G4)
riskforge tests generate <system-id>

# 6. Check readiness (exit 1 if a FAIL gate is unmet)
riskforge validate <system-id>

# 7. Create a signing key once, outside the project (keygen never overwrites a file)
mkdir -p ~/.config/riskforge
riskforge keygen --output ~/.config/riskforge/signing.pem

# 8. Export the RMF, signing the JSON
riskforge export <system-id> --format json --output rmf.json --sign ~/.config/riskforge/signing.pem
riskforge export <system-id> --format pdf --output rmf.pdf

# 9. Take a receipt and keep it outside the project
riskforge receipt <system-id> --output receipt-2026-q4.json

# 10. Verify later (exit 2 if anything was altered)
riskforge verify
riskforge verify --file rmf.json --trusted-key ~/.config/riskforge/signing.pem.pub
riskforge verify --receipt receipt-2026-q4.json
```

The Annex III category is one of: `biometric`, `critical_infrastructure`,
`education`, `employment`, `essential_services`, `law_enforcement`, `migration`,
`justice`. A category plus matching purpose keywords triggers a pre-built risk
pattern (for example, `employment` + "hiring/resume/screening" triggers the hiring
pattern), whose risk items are added for your confirmation. A keyword matches the
start of a word or phrase in the purpose, so "credit" matches "Creditworthiness".
The medical diagnosis pattern follows the Article 6(1) route (an AI system that
is, or is a safety component of, a product covered by the Annex I legislation and
that is required to undergo a third-party conformity assessment: Art.6(1)(a) and
(b)) and needs no category: purpose keywords such as "medical diagnosis" or
"radiology" trigger it.

---

## Non-interactive assessment

`assess` is interactive by default. For CI, reproducible fixtures, or scripted
sample data, drive it from a YAML answers file:

```bash
riskforge assess <system-id> \
  -a "Dr. Lena Fischer" -r "AI Governance Lead" \
  --answers answers.yaml
```

```yaml
# answers.yaml
add_patterns: true          # inject matched Annex III patterns (default true)
answers:
  PR-001: { applies: yes, likelihood: 4, severity: 5 }   # yes | no | unknown | skip
  HS-001: { applies: unknown }        # knowledge gap (uses the question's hints)
  DI-001: { applies: no }             # not applicable
  # questions omitted from the file default to "skip"
```

`applies: yes` adds a scored risk item (likelihood and severity required).
`applies: unknown` flags a knowledge gap; `riskforge tests generate` then saves a test requirement for it.
Question ids come from the bundled question bank (see the files under
`src/riskforge/_data/question_bank/`).

Running `assess` again, with the same file or interactively, updates the register
instead of adding to it. Each item is matched to the question or pattern risk it
came from. An unchanged answer changes nothing and records nothing. A changed
answer updates the item's likelihood, severity and knowledge-gap flag and records
`risk_item.updated`. The residual scores follow only while the item has no
mitigation and its residual scores were never changed. An acceptance is kept, and
`assess` prints a line asking you to review the item. `assess` never removes an
item: if a question is now answered `no` or `skip`, or left out of the answers file,
its item stays and is listed so you can review it. A register that RiskForge 1.1.3
already doubled keeps its duplicates: `assess` updates the first item for each
question or pattern risk and lists the others so you can review them.

---

## Command reference

| Command | What it does |
|---|---|
| `riskforge init -n NAME -s VERSION -p PURPOSE --provider ORG [-c CATEGORY]` | Create a project and register a system; prints the system id. |
| `riskforge system show <id>` | Print the system record as JSON. |
| `riskforge system classify <id> --confirm [-c CATEGORY]` | Record the Article 6(2) Annex III self-classification (clears gate G2), audited. |
| `riskforge assess <id> -a NAME -r ROLE [--dimension DIM] [--answers FILE]` | Run the assessment, interactive or from an answers file. |
| `riskforge risk list <id> [-d DIMENSION]` | List risk items (id, dimension, score, band, accepted). |
| `riskforge risk mitigate <id> <risk-id> -m DESC -c TYPE --owner OWNER --by NAME [--status S] [--residual-likelihood N] [--residual-severity N]` | Add a mitigation and optionally re-score residual risk, audited, with who recorded it. |
| `riskforge risk accept <id> <risk-id> -r RATIONALE --by NAME` | Accept a residual risk with a documented rationale, audited, with who accepted it. |
| `riskforge tests generate <id>` | Derive Article 9(6) to 9(8) test requirements from knowledge-gap risks and risks whose inherent score is 9 or more, and save them on the register. Run it before `export`: the export carries the saved requirements. |
| `riskforge validate <id> [--force]` | Run the 8 readiness gates. |
| `riskforge export <id> [-f json\|pdf\|markdown] [-o PATH] [--sign KEYFILE] [--public-key PUBFILE] [--force]` | Export the RMF, see [Exporting the RMF](#exporting-the-rmf). |
| `riskforge verify [--file rmf.json] [--strict] [--receipt FILE]... [--trusted-key PUBFILE]... [--project-dir DIR]` | Verify the audit chain, or a standalone exported RMF with `--file` (see [Verifying an exported file](#verifying-an-exported-file)). `--strict` fails on integrity warnings too. `--receipt` and `--trusted-key` are described under [Receipts](#receipts-a-record-kept-outside-the-project). |
| `riskforge keygen --output KEYFILE` | Create an Ed25519 key pair: `KEYFILE` (mode 600 on Linux and macOS, not encrypted) and `KEYFILE.pub`. Never overwrites a file. |
| `riskforge receipt <id> [-o FILE] [--sign KEYFILE]` | Take a receipt for the last audit entry, to keep outside the project. |
| `riskforge diff <id> BASELINE.json COMPARISON.json` | Show the items added, removed and changed between two exported RMFs, with each changed field. |
| `riskforge import <id> -a ADAPTER -r REPORT.json` | Import an upstream tool report (adapters: `rag-benchmarking`, `traceforge`). |

Risk ids accept the first 8 characters shown by `riskforge risk list`.

### Exporting the RMF

```bash
riskforge export <id> -f json -o rmf.json            # the gates must pass, or add --force
riskforge export <id> -f pdf -o rmf.pdf --sign k.pem  # signed with a key from riskforge keygen
```

An export holds the project lock from start to finish and runs in this order:

1. The project is checked as `riskforge verify` checks it. A project that fails exits 2.
2. The validation gates run, unless `--force` is given. A FAIL gate exits 1.
3. If the register was last written by RiskForge 1.1.3 or by an older model, it is
   rewritten in the current format and a `register.checkpoint` entry is prepared for it.
   No value changes.
4. The document is built: the content and its digest, the chain proof, the receipt and,
   with `--sign`, the signature. It must validate against RMF schema 1.1.0.
5. The whole file is rendered and written to a temporary file next to the output path,
   readable only by its owner on Linux and macOS.
6. The checkpoint, if any, is committed to the audit log, the temporary file is renamed
   to the output path, and only then is `rmf.exported` recorded, with the content digest
   (`sha256`) and the SHA-256 of the file (`file_sha256`).

If anything fails before step 6, such as a missing output directory, no file is written
and nothing is recorded, not even the checkpoint. A temporary file left by an
interrupted export (its name starts with `.riskforge-export-`) is removed by a later
export to the same directory if it is older than that export's hold on the project lock.

The JSON, PDF and Markdown exports of one register state show the same content digest,
and two exports of an unchanged register share it, so a PDF can be matched to the JSON
export you verified by comparing digests. To match any exported file to its audit entry,
hash it and compare the result with `file_sha256`: `sha256sum rmf.pdf` (on macOS,
`shasum -a 256 rmf.pdf`).

`--sign KEYFILE` takes an Ed25519 private key file created by `riskforge keygen`. The
export carries the signature in `signatures` and the public key in `public_keys`, and its
receipt is signed with the same key. RiskForge no longer signs with GPG: a value that is
not a key file, such as a GPG key id, exits 3 and nothing is written. On Linux and macOS
a key file that its group or other users can read is refused (`chmod 600 FILE`).

The `riskforge` CLI does not sign audit entries, but a project written through the Python API
can hold entries signed by another key. The export embeds the public key of every signed
entry in its `public_keys` block, so give each one with `--public-key PUBFILE` (repeatable). Without
it the export exits 3, names the entry, and writes nothing.

### Who accepted a risk or recorded a mitigation

`risk accept` and `risk mitigate` require a name, given as `--by "Name, Role"`.
In CI you can set the `RISKFORGE_ACTOR` environment variable instead; when both
are set, `--by` wins. With neither, or with a blank value, the command changes
nothing and exits 3. The name must be plain text on one line: line breaks, control
characters, bidirectional controls, zero-width space, LRM, RLM and BOM are refused
with exit 3.

The name is self-declared. RiskForge records it as given and does not check who
ran the command. It becomes the audit entry's actor and is stored on the risk item
as `accepted_by` or on the mitigation as `recorded_by`. The Markdown and PDF
exports show it as "Accepted by" and "Recorded by", and the JSON export (RMF schema
1.1.0) holds both fields, so the content digest every format shows covers them.
Acceptances recorded before 2.0.0 show "Accepted by: not recorded".

### Receipts: a record kept outside the project

`riskforge verify` compares the audit log with `.riskforge/audit.head.json`, which
records where the log ends. Someone who cuts entries off the end of the log, puts
the files back as they were, and rewrites the head file to match, passes that check
(ADR-03 records this limit). A receipt closes the gap. It names the `seq` and
`entry_hash` of the last audit entry when it was taken, and the latest register
fingerprint the log records for the system. Keep it somewhere the project's owner
cannot change, for example with your auditor or client.

```bash
riskforge receipt <id> -o receipt-2026-q4.json              # unsigned
riskforge receipt <id> -o receipt-2026-q4.json --sign k.pem # signed with a key from riskforge keygen
riskforge verify --receipt receipt-2026-q4.json             # exit 2 once the log no longer holds that entry
riskforge verify --receipt receipt-2026-q4.json --trusted-key k.pem.pub
```

- `receipt` runs the same integrity check as `verify` first and takes nothing from
  a project that fails it (exit 2). It only reads the project. Without `-o` it
  prints the receipt as JSON. With `-o` it creates the file with mode 600 on Linux
  and macOS, and never overwrites a file (exit 3).
- `verify --receipt FILE` can be given more than once. It exits 2 when the audit log
  has no entry at the receipt's `seq` (the log was truncated or replaced) or holds a
  different entry there (it was rewritten). It also exits 2 when the receipt's
  register fingerprint is not the last one the log records for its system up to
  that `seq`. A receipt proves the entries up to its `seq` only. `verify` does not
  compare its register fingerprint with today's register, which may have changed
  since for good reasons.
- A signed receipt carries its key id, public key and signature, and must verify
  with that public key. That proves only that whoever held the key signed it. To
  check who signed it, pass the signer's public key with `--trusted-key PUBFILE`
  (repeatable): the receipt must then be signed by one of those keys, so an unsigned
  receipt, or one signed by another key, exits 2.
- A receipt file is refused with exit 2 if it holds a field RiskForge does not
  write, the same key twice in one object, or a number such as `NaN`. A file that is
  not JSON, or not a receipt, exits 3. With `--file`, `--receipt` and
  `--trusted-key` check an exported file instead of the project, see
  [Verifying an exported file](#verifying-an-exported-file).
- `--trusted-key` also checks signed audit entries. The `riskforge` CLI does not sign
  audit entries, but a log written by other tools may hold signed ones. Without
  `--trusted-key`, `verify` warns that their signatures were not checked, and
  `--strict` fails on that warning.
- With `--trusted-key`, `verify` warns how many audit entries are not signed, and
  `verify --strict --trusted-key` fails on them, so it passes only on a log whose
  entries are all signed.

### The 8 validation gates

| Gate | Check | On failure |
|---|---|---|
| G1 | All 8 dimensions have at least one entry | FAIL |
| G2 | Article 6(2) self-classification documented | FAIL |
| G3 | Residual score above the risk-appetite threshold must be reduced (re-scored with `risk mitigate --residual-likelihood`/`--residual-severity`) or accepted; adding a mitigation without re-scoring does not clear it | FAIL |
| G4 | Knowledge gaps have test requirements | WARN |
| G5 | System metadata complete | FAIL |
| G6 | Assessor identity recorded | FAIL |
| G7 | Risk-score distribution plausible | WARN |
| G8 | No vague mitigation language | WARN |

FAIL gates block export unless you pass `--force`. WARN gates are advisory.

---

## Exit codes (for CI)

| Code | Meaning |
|---|---|
| 0 | Success or valid |
| 1 | A validation FAIL gate without `--force`; `validate` finding a change in progress or unfinished; `verify` finding a change in progress (`txn.json`) whose recovered state has no finding; a command that waited more than 120 seconds for another `riskforge` process to release the project; an export that could not be built (nothing is written); or an unexpected crash (prints a traceback) |
| 2 | Integrity failure: audit chain corrupt or tampered, a register or system file changed outside RiskForge, a deleted or cut-off log, an RMF file that does not match its digest, signatures, chain proof or receipt, a receipt the audit log or the file's chain proof no longer holds, a change in progress whose recovered state has a finding, a `txn.json` that RiskForge did not write, or a receipt, RMF, sign-off or audit entry signature that fails or is not from a trusted key; with `verify --strict`, also any integrity warning. Commands that change or export data exit 2 on such a project and change nothing |
| 3 | Usage or input error: unknown option or command, bad option value, missing or malformed input file, unknown system or risk id, no project, no risk register yet, project already exists, `system classify` without `--confirm`, an `export --sign` or `--public-key` value that is not a usable Ed25519 key file, an export of a project with a signed audit entry whose public key was not given with `--public-key`, an export output directory that is missing or cannot be written, `verify --strict` with `--file`, a receipt file that is not JSON or not a receipt, a `--trusted-key` file that is not an Ed25519 public key, an existing `receipt -o` file, or interactive `assess` without a terminal |

`verify` returns 2 on any integrity finding, which makes it usable as a CI gate. A typo in a flag
exits 3, never 2, so a usage error cannot be mistaken for tampering.

---

## Continuous integration recipe

The files in `.riskforge/` hold your risk assessment: risk descriptions, rationales
and assessor names. Inside a git repository, `riskforge init` warns when
`riskforge.yaml` is not git-ignored; add `.riskforge/` and `riskforge.yaml` to
`.gitignore`. If your repository is private and you want CI to check the project,
commit them and the exported `rmf.json` on purpose; never do this in a public
repository. Then fail the build if the project or the export was altered:

```yaml
- run: pip install riskforge
- run: riskforge verify --strict        # project intact (exit 2 on tamper or warning)
- run: riskforge verify --file rmf.json --trusted-key signing.pem.pub  # export signed by your key
```

Commit only the public key (`signing.pem.pub`); the private key never goes into a
repository.

To re-run an assessment on a model change without a human at the terminal, keep an
`answers.yaml` next to the project and run
`riskforge assess <id> -a NAME -r ROLE --answers answers.yaml`, then
`riskforge tests generate <id>` and `riskforge validate <id>`. The re-run updates
the items it created earlier and adds none twice; an accepted item whose answer
changed stays accepted and is listed for review (see
[Non-interactive assessment](#non-interactive-assessment)).

Only one process or person should change a project at a time. RiskForge serializes
writers on one machine with a file lock, but two git branches that both changed
`.riskforge/` cannot be merged: the merged audit log no longer forms one chain, and
`riskforge verify` exits 2.

A project last written by RiskForge 1.1.3 passes `riskforge verify` with a warning on
stderr until its next change, because its registers are not yet covered by a
fingerprint and it has no `.riskforge/audit.head.json` yet. To fail the build on that, or on any other integrity warning, run
`riskforge verify --strict`: it exits 2 and lists each warning as a finding on its own
line. A change in progress exits 1 when the project, as the next command would recover
it, is clean, and 2 when that view has a finding. A file check has no warnings, so `--strict`
with `--file` exits 3.

If your CI pipeline exports PDF reports (`riskforge export -f pdf`), install the
system dependencies prior to running `riskforge`:
- Linux runners (`ubuntu-latest`): `sudo apt-get update && sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info`
- macOS runners (`macos-latest`): `brew install pango cairo gdk-pixbuf libffi`

---

## Interpreting the RMF

The JSON RMF declares RMF schema 1.1.0 and has these top-level fields: `id`,
`rmf_schema_version`, `register`, `test_requirements`, `cross_references`,
`generated_at`, `sha256_hash`, `disclosure`, `signoffs`, `signatures`,
`public_keys`, `chain_proof` and `receipt` (schema `$id`
`https://aiexponent.com/schemas/riskforge/rmf/1.1.0.json`). The `register` holds
the system record, the risk items, the saved test requirements, the assessor,
dates, and the risk-appetite threshold. Each risk item carries its dimension,
scoring, mitigations, residual scoring, acceptance, and Article/NIST/ISO references,
with `accepted_by` and `recorded_by` when a name was recorded.

`sha256_hash` is the content digest: the SHA-256 of the document without `id`,
`generated_at`, `sha256_hash`, `signatures`, `public_keys`, `chain_proof` and
`receipt`, so `riskforge verify --file` can recompute and confirm it.

`chain_proof` holds every entry of the project audit log up to the export (the export's
own `rmf.exported` entry is recorded after the file is written, so it is never in the
file), and `receipt` names the last of those entries. `signatures` and `public_keys` are
filled when the export is signed with `--sign`. The `riskforge` CLI writes `signoffs` as an
empty list.

A file written by RiskForge 1.1.3 or earlier declares RMF schema 1.0.0. `verify
--file` checks its digest by the rule those releases used: the whole document with
`sha256_hash`, `audit_entry_hash` and `signed_by` blanked. See
[Verifying an exported file](#verifying-an-exported-file) for everything `verify
--file` checks. The JSON Schemas are bundled as `rmf-1.0.0.schema.json` and
`rmf-1.1.0.schema.json` in `riskforge/_data/schemas/`.

### Verifying an exported file

```bash
riskforge verify --file rmf.json                                  # exit 2 if anything fails
riskforge verify --file rmf.json --trusted-key k.pem.pub          # and the signer must be this key
riskforge verify --file rmf-2027-q1.json --receipt rmf-2026-q4.json  # an older receipt still holds
```

`verify --file` needs only the JSON export, not the project. It reads the file
strictly: a duplicate key, `NaN`, `Infinity`, a number such as `1e400`, an integer
too long to read or arrays and objects nested more than 64 levels deep exits 2, and a
file that is not JSON, or declares a schema version RiskForge does not read, exits 3. For an RMF schema 1.1.0 file it then checks, in
this order, and lists every failure it finds:

1. The file validates against the schema it declares, and `sha256_hash` equals the
   content digest. A file that does not validate gets no further checks.
2. Each `public_keys` record has its own key id, and that key id is the one derived
   from its public key.
3. Each RMF signature names a key in `public_keys` and verifies over the content digest.
4. Each sign-off names a key in `public_keys`, its signature verifies, and it is for
   the register in the file (its `register_fingerprint`).
5. The chain proof links and hashes check from `seq` 0, every signed entry verifies,
   and the last register fingerprint it records for the system is the register in the
   file.
6. The embedded receipt names the last chain proof entry, the file's system and the
   register in the file, and verifies when it is signed.
7. Each `--receipt FILE` (a receipt file, or an older export whose receipt is used)
   holds against the file's chain proof, as `verify --receipt` checks the audit log.

What each check catches when the file is checked alone:

| Record | Catches | Does not catch |
|---|---|---|
| Content digest | A change to the content by someone who did not recompute the digest | Anyone can recompute it |
| Chain proof | A register that is not the state the audit log recorded last, and edited, missing or reordered entries | A chain proof rebuilt to agree with an edited register |
| Embedded receipt | A chain proof whose last entry is not the one the receipt names, including entries added after it | A receipt rebuilt along with the chain proof, unless a trusted key signed it |
| RMF signature with `--trusted-key` | Any change to the content, since the trusted key signed the digest | Changes to the blocks the digest leaves out, which the chain proof and receipt checks tie to the content |
| RMF signature without `--trusted-key` | Nothing about who signed: anyone can sign with a new key and embed it | |

Without `--trusted-key`, a signature that verifies shows only that whoever holds the
embedded key signed. A sign-off is no different: "approved by Chief Risk Officer"
signed with a key embedded in the file shows only that someone with that key wrote it.
With `--trusted-key PUBFILE` (repeatable), the file must carry an RMF signature, and
every RMF signature, sign-off and the embedded receipt must be signed by one of the
trusted keys. A signed chain proof entry must verify, but its key need not be trusted:
the trusted receipt covers the chain proof.

What a pass prints says how much it proves:

- With `--trusted-key`, and a trusted key signed the file, the first line is "RMF
  integrity verified".
- Without `--trusted-key`, the first line is "RMF file is internally consistent". Each
  RMF signature and sign-off that verifies with an embedded key says so, and the last
  line says that anyone can rebuild the chain proof, receipt and signatures, and to
  pass `--trusted-key` (and `--receipt` with a receipt kept elsewhere) to check who
  made the file.
- With `--receipt`, when the chain proof records the file's register after the
  receipt's `seq`, a note says the receipt does not cover the register in the file and
  how many entries come after it. The check still passes: a receipt proves only the
  entries up to its `seq`, and a later register is not a failure in itself.

The pass and its notes go to stdout. A failure, including a file refused when it is
read, goes to stderr, as it does for the project check.

A file that declares RMF schema 1.0.0 cannot carry a signature, a chain proof or a
receipt. Plain `verify --file` checks its schema and digest only and says so. With
`--trusted-key` or `--receipt` it exits 2 with "RMF schema 1.0.0 cannot carry a
signature", because otherwise a 1.1.0 file could be rewritten as 1.0.0, with its
signature, chain proof and receipt dropped and its digest recomputed, and pass. If you
rely on a file, check it with `--trusted-key` or `--receipt`.

Only the JSON export can be checked this way. To check a PDF or Markdown export,
compare the digest it shows with a verified JSON export of the same register, or hash
the file and compare with `file_sha256` in the audit log.

The PDF renders the same data in seven parts: a cover with a three-number summary
and the content digest, an executive summary ending with the disclosure, the
methodology, the full register, a residual-risk summary, the test requirements,
and the audit metadata with a change log.

---

## Extending RiskForge (plugins)

RiskForge discovers question banks, exporters, and adapters through Python
entry points, so you extend it by `pip install`-ing a package, with no config edit.

- **Question banks:** entry-point group `riskforge.question_banks`, loaded but not used
  by `assess` yet: `assess` asks only the bundled questions. The simplest
  contribution needs zero Python: add a question to a YAML file under
  `src/riskforge/_data/question_bank/` and open a PR. See
  [`docs/contributing/add-question.md`](contributing/add-question.md).
- **Risk patterns:** add a YAML block to `src/riskforge/_data/patterns/patterns.yaml`.
  See [`docs/contributing/add-pattern.md`](contributing/add-pattern.md).
- **Exporters:** entry-point group `riskforge.exporters` (json, pdf, markdown ship
  built in). See [`docs/contributing/add-exporter.md`](contributing/add-exporter.md).
- **Adapters:** entry-point group `riskforge.adapters` (rag-benchmarking and
  traceforge ship built in).

---

## Limitations and disclosure

- RiskForge is not a legal compliance determination and not legal advice.
- It is not a notified-body conformity assessment. The RMF is one input to that
  separate process.
- It does not decide whether a system is high-risk under Annex III. It records the
  provider's Article 6(2) self-classification (gate G2); it does not make it.

Every export carries this disclosure, which RiskForge always includes and no option
removes (it is part of the content digest): the document was produced using
RiskForge, represents the team's documented risk assessment, has not been reviewed
by a qualified legal professional, and does not constitute legal advice.

---

## FAQ

**Does my risk data leave my machine?** No. RiskForge makes zero outbound calls.

**Can I edit the state files by hand?** They are plain YAML and JSONL, readable and
diff-able. Editing the `.riskforge/audit.jsonl` chain, a register or a system file
by hand is detected by `riskforge verify` (exit 2) unless the chain and head file are
recomputed to match; a receipt kept elsewhere catches that for the entries it covers.
Once detected, every command that changes or
exports data then refuses the project with exit 2 and changes nothing. Make changes
through the CLI.

**Why does validation fail with G2 even after `init`?** `init` records the Annex III
category but not the self-classification confirmation. Run
`riskforge system classify <id> --confirm` to clear G2.

**Where do exports go by default?** To the project directory, named
`rmf-<id-prefix>-<export-id>.<ext>`, unless you pass `--output`.

**How do I re-assess on a model change?** Keep an `answers.yaml` and run
`riskforge assess <id> -a NAME -r ROLE --answers answers.yaml`, then
`tests generate`, `validate` and `export`. The re-run updates the existing items
instead of adding them again, and never removes one: review the items it lists,
and the accepted items whose scores changed, before you export.

**How do I show later that the history was not rewritten?** Run
`riskforge receipt <id> --output FILE` after an export and keep the file somewhere
the project's editors cannot change, for example with your client or auditor.
`riskforge verify --receipt FILE` exits 2 if the log no longer holds that entry,
even when every file in the project was rewritten to match. Entries written after
the receipt are not covered, so take a new receipt after each export.

**Where do I keep the signing key?** Outside the project and out of version
control, for example in `~/.config/riskforge/`. Give the `.pub` file to whoever
checks your exports; they pass it to `verify --file --trusted-key`.
