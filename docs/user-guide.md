# RiskForge user guide

RiskForge is an open-source command-line tool that turns EU AI Act Article 9 risk
management into a developer workflow. You run a guided assessment across 8 risk
dimensions, score and treat each risk, and export a tamper-evident **Risk
Management File** (RMF) shaped for an Annex IV technical documentation pack.

RiskForge is not legal advice and not a notified-body conformity assessment. Every
export carries a non-removable disclosure to that effect.

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
  hash-chained log, so tampering is detectable with `riskforge verify`.

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

# 5. Check readiness (exit 1 if a FAIL gate is unmet)
riskforge validate <system-id>

# 6. Export the RMF
riskforge export <system-id> --format pdf --output rmf.pdf
riskforge export <system-id> --format json --output rmf.json

# 7. Verify integrity later (exit 2 if tampered)
riskforge verify --file rmf.json
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
  DISC-001: { applies: no }           # not applicable
  # questions omitted from the file default to "skip"
```

`applies: yes` adds a scored risk item (likelihood and severity required).
`applies: unknown` flags a knowledge gap and derives a test requirement later.
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
| `riskforge tests generate <id>` | Derive Article 9(6) to 9(8) test requirements from open and knowledge-gap risks. |
| `riskforge validate <id> [--force]` | Run the 8 readiness gates. |
| `riskforge export <id> [-f json\|pdf\|markdown] [-o PATH] [--sign KEYID] [--force]` | Export the RMF. |
| `riskforge verify [--file rmf.json] [--strict] [--receipt FILE]... [--trusted-key PUBFILE]... [--project-dir DIR]` | Verify the audit chain, or a standalone RMF's digest with `--file`. `--strict` fails on integrity warnings too. `--receipt` and `--trusted-key` are described under [Receipts](#receipts-a-record-kept-outside-the-project). |
| `riskforge receipt <id> [-o FILE] [--sign KEYFILE]` | Take a receipt for the last audit entry, to keep outside the project. |
| `riskforge diff <id> BASELINE.json COMPARISON.json` | Show the items added, removed and changed between two exported RMFs, with each changed field. |
| `riskforge import <id> -a ADAPTER -r REPORT.json` | Import an upstream tool report (adapters: `rag-benchmarking`, `traceforge`). |

Risk ids accept the first 8 characters shown by `riskforge risk list`. The
`--sign` value is a GPG key identifier (email, key id, or fingerprint), not a file
path; signing produces a detached `.asc` next to the export.

### Who accepted a risk or recorded a mitigation

`risk accept` and `risk mitigate` require a name, given as `--by "Name, Role"`.
In CI you can set the `RISKFORGE_ACTOR` environment variable instead; when both
are set, `--by` wins. With neither, or with a blank value, the command changes
nothing and exits 3. The name must be plain text on one line: line breaks, control
characters, bidirectional controls and invisible characters other than zero-width
joiners are refused with exit 3.

The name is self-declared. RiskForge records it as given and does not check who
ran the command. It becomes the audit entry's actor and is stored on the risk item
as `accepted_by` or on the mitigation as `recorded_by`. The Markdown and PDF
exports show it as "Accepted by" and "Recorded by". The JSON export (RMF schema
1.0.0) does not include these two fields yet. The SHA-256 that the Markdown and
PDF exports show (the PDF labels it "Document SHA-256") is the hash of the JSON
export, so it does not cover the "Accepted by" and "Recorded by" text until a later RMF
schema (1.1.0). Acceptances recorded before 2.0.0 show "Accepted by: not
recorded".

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
  different entry there (it was rewritten). A receipt proves the entries up to its
  `seq` only. `verify` does not compare its register fingerprint with today's
  register, which may have changed since for good reasons.
- A signed receipt carries its key id, public key and signature, and must verify
  with that public key. That proves only that whoever held the key signed it. To
  check who signed it, pass the signer's public key with `--trusted-key PUBFILE`
  (repeatable): the receipt must then be signed by one of those keys, so an unsigned
  receipt, or one signed by another key, exits 2.
- A receipt file is refused with exit 2 if it holds a field RiskForge does not
  write, the same key twice in one object, or a number such as `NaN`. A file that is
  not JSON, or not a receipt, exits 3. `--receipt` and `--trusted-key` check a
  project and cannot be combined with `--file` yet.
- `--trusted-key` also checks signed audit entries. The `riskforge` CLI does not sign
  audit entries, but a log written by other tools may hold signed ones. Without
  `--trusted-key`, `verify` warns that their signatures were not checked, and
  `--strict` fails on that warning.

### The 8 validation gates

| Gate | Check | On failure |
|---|---|---|
| G1 | All 8 dimensions have at least one entry | FAIL |
| G2 | Article 6(2) self-classification documented | FAIL |
| G3 | Above-threshold risks mitigated or accepted | FAIL |
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
| 1 | A validation FAIL gate without `--force`; `verify`, `validate` or `tests generate` finding a change in progress or unfinished; a command that waited more than 120 seconds for another `riskforge` process to release the project; or an unexpected crash (prints a traceback) |
| 2 | Integrity failure: audit chain corrupt or tampered, a register or system file changed outside RiskForge, a deleted or cut-off log, an RMF file that does not match its digest, a receipt the audit log no longer holds, or a receipt or audit entry signature that fails or is not from a trusted key; with `verify --strict`, also any integrity warning. Commands that change or export data exit 2 on such a project and change nothing |
| 3 | Usage or input error: unknown option or command, bad option value, missing or malformed input file, unknown system or risk id, no project, no risk register yet, project already exists, `system classify` without `--confirm`, a failed `export --sign`, `verify --strict`, `--receipt` or `--trusted-key` with `--file`, a receipt file that is not JSON or not a receipt, a `--trusted-key` file that is not an Ed25519 public key, an existing `receipt -o` file, or interactive `assess` without a terminal |

`verify` returns 2 on any tamper, which makes it usable as a CI gate. A typo in a flag
exits 3, never 2, so a usage error cannot be mistaken for tampering.

---

## Continuous integration recipe

Store the `.riskforge/` directory and the exported `rmf.json` in your repository,
then fail the build if either the audit chain or the exported file has been altered:

```yaml
- run: pip install riskforge
- run: riskforge verify                 # audit chain intact (exit 2 on tamper)
- run: riskforge verify --file rmf.json  # exported RMF matches its digest
```

To re-run an assessment on a model change without a human at the terminal, keep an
`answers.yaml` in the repo and run `riskforge assess <id> --answers answers.yaml`
followed by `riskforge validate <id>`.

A project last written by RiskForge 1.1.3 passes `riskforge verify` with a warning on
stderr until its next change, because its registers are not yet covered by a
fingerprint and it has no `.riskforge/audit.head.json` yet. To fail the build on that, or on any other integrity warning, run
`riskforge verify --strict`: it exits 2 and lists each warning as a finding on its own
line. A change in progress still exits 1. `--strict` checks a project only, so with
`--file` it exits 3.

If your CI pipeline exports PDF reports (`riskforge export -f pdf`), install the
system dependencies prior to running `riskforge`:
- Linux runners (`ubuntu-latest`): `sudo apt-get update && sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info`
- macOS runners (`macos-latest`): `brew install pango cairo gdk-pixbuf libffi`

---

## Interpreting the RMF

The JSON RMF has these top-level fields: `id`, `rmf_schema_version`, `register`,
`test_requirements`, `cross_references`, `generated_at`, `sha256_hash`, `signed_by`,
`audit_entry_hash`, and `disclosure`. The `register` holds the system record, the
risk items, the assessor, dates, and the risk-appetite threshold. Each risk item
carries its dimension, scoring, mitigations, residual scoring, acceptance, and
Article/NIST/ISO references.

`sha256_hash` is computed over the document content with the integrity fields
(`sha256_hash`, `audit_entry_hash`, `signed_by`) blanked, so `riskforge verify
--file` can recompute and confirm it. `audit_entry_hash` links the file to the
`rmf.exported` entry in the audit chain.

The PDF renders the same data as a filing-ready document: cover, executive summary,
risk register, test requirements, audit trail, and the mandatory disclosure.

---

## Extending RiskForge (plugins)

RiskForge discovers question banks, exporters, and adapters through Python
entry points, so you extend it by `pip install`-ing a package, with no config edit.

- **Question banks:** entry-point group `riskforge.question_banks`. The simplest
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

Every export carries this non-removable disclosure: the document was produced using
RiskForge, represents the team's documented risk assessment, has not been reviewed
by a qualified legal professional, and does not constitute legal advice.

---

## FAQ

**Does my risk data leave my machine?** No. RiskForge makes zero outbound calls.

**Can I edit the state files by hand?** They are plain YAML and JSONL, readable and
diff-able. Editing the `.riskforge/audit.jsonl` chain, a register or a system file
by hand is detected by `riskforge verify` (exit 2), and every command that changes or
exports data then refuses the project with exit 2 and changes nothing. Make changes
through the CLI.

**Why does validation fail with G2 even after `init`?** `init` records the Annex III
category but not the self-classification confirmation. Run
`riskforge system classify <id> --confirm` to clear G2.

**Where do exports go by default?** To the project directory, named
`rmf-<id-prefix>-<export-id>.<ext>`, unless you pass `--output`.

**How do I re-assess on a model change?** Keep an `answers.yaml` and run
`riskforge assess <id> --answers answers.yaml`, then `validate` and `export`.
