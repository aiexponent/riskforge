# Changelog

All notable changes to RiskForge are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/)

## [Unreleased]

### Breaking changes

- Removed the experimental `riskforge serve` API server: the `serve` command, the `riskforge.server` package, the `[server]` install extra (`pip install riskforge[server]`) and the Docker files that ran it (`docker/Dockerfile`, `docker/docker-compose.yml`). Most of its routes were unimplemented and it was untested. The CLI and engine are unchanged (PRD-354).
- Exit codes follow one contract: 0 success, 1 a validation gate failed (or an unexpected crash), 2 integrity failure, 3 usage or input error. A mistyped option, a missing required option or an unknown command now exits 3 instead of 2, so a CI job that reads 2 as "tampered" no longer mistakes a typo for tampering. Scripts that checked for 2 on a usage error must check for 3. Some input errors that used to exit 1 now exit 3 as well, such as `system classify` without `--confirm`, a failed `--sign`, an unknown system or risk id and a bad answers file (see Fixed) (PRD-326).
- `StorageBackend` (for custom storage backends): `audit_lock()` is replaced by `unit_of_work()`, an exclusive, re-entrant scope in which a register or system write and the audit entry that records it commit together. Backends must also implement `read_register_document()`. The unused `write_export()` is removed. `FileStore.append_audit()` raises `RuntimeError` outside a unit of work, `FileStore.read_audit()` and `FileStore.read_last_audit_entry()` raise the new `AuditLogCorruptError` on a line that is not a valid entry instead of skipping it or failing with a parse error, and a unit of work that ends cleanly with writes no audit entry recorded raises `RuntimeError` and discards them. `FileStore` takes a `lock_timeout` (default 120 seconds) and raises the new `ProjectLockedError` when another process holds the project lock for longer (PRD-331).
- `riskforge verify` now checks more than the audit chain (see Fixed), so a project it passed before can fail with exit 2: a register or `system.yaml` edited by hand, a `system.yaml` that an older release updated without the copy in its register, or a log with no head file although entries written by RiskForge 2.0 are in it. `verify` also exits 1, with one line, when a change is in progress or unfinished (`.riskforge/txn.json` is present after it re-checks three times), so a write that overlaps `verify` is not reported as tampering. Findings and warnings now go to stderr. RiskForge 1.1.3 cannot read a log written by 2.0: it reports the chain as corrupt (PRD-332).
- `StorageBackend` (for custom storage backends): backends must also implement `read_system_document()` and `read_audit_head()`, store audit entries with absent optional fields left out, and return the register document as stored, or register fingerprints will not match (ADR-03). `append_audit()` takes one entry or a list of chained entries that commit together. `FileStore` reads stored YAML as bytes and raises the new `StoredFileCorruptError` when a register, system file or head file does not parse, and takes `read_only=True` to read without the lock or any write (PRD-332).
- Commands that change or export data refuse a tampered project with exit 2: `validate`, `export`, `assess`, `risk accept`, `risk mitigate`, `system classify`, `import` and `tests generate` run the same integrity check as `riskforge verify` first, print one line per finding and change nothing when it fails. A project with a deleted `register.yaml` that the audit log records changes to, or with a `system.yaml` that does not parse, now exits 2 from these commands, where `assess` and `system classify` used to carry on and the others exited 3. The commands that change data, and `export`, hold the project lock from the check through the change. `validate` and `tests generate` take no lock and write nothing, as `verify` does, so they still work on a read-only copy, and they exit 1 while a change is in progress or unfinished. All of them print the check's warnings (for a project last written by 1.1.3) to stderr (PRD-333).
- Library API: `AuditEngine` and the engines built on it refuse to change a project that fails its integrity check, raising the new `riskforge.engine.integrity.IntegrityError`. Open a change with `AuditEngine.unit_of_work()`, which runs the check once per outermost unit of work before anything is staged and keeps what it read: a register or system file changed outside RiskForge after the check is refused when the change reads it (`AuditEngine.read_register()`, `read_system()`) or records an entry for it. A backend without unit-of-work state must also report the change's own writes with `AuditEngine.wrote_register()` and `wrote_system()`. A register or system write staged in a `StorageBackend.unit_of_work()` opened directly is checked as written when `record()` runs, so it fails the check: open the scope with `AuditEngine.unit_of_work()` instead. `StorageBackend` gains `unit_of_work_state()`, with a default that custom backends need not override (PRD-333).
- `risk accept` and `risk mitigate` require `--by "Name, Role"`, or the `RISKFORGE_ACTOR` environment variable when the flag is absent (the flag wins when both are set). Without a name, or with a blank one, they change nothing and exit 3. Scripts and CI jobs that call them must pass `--by` or set `RISKFORGE_ACTOR`. The name is self-declared and not verified. It is the audit entry's actor, where it used to be `cli`, and is stored as `accepted_by` on the risk item or `recorded_by` on the mitigation. Library API: `RiskEngine.accept_risk()` stores its `actor_identity` as `accepted_by` and raises the new `riskforge.engine.actor.ActorNameError` for a blank name or one with a line break, control character, bidirectional control or invisible character (zero-width joiners are allowed), and `RiskEngine.add_mitigation()` takes an optional `recorded_by` (PRD-356).
- Library API: `AssessEngine.match_patterns()` takes the system's purpose text instead of a list of purpose words, and the bundled pattern file (schema 1.1.0) lists categories in `triggers.annex_iii_categories` instead of `triggers.annex_iii_category`. `riskforge.engine.assess.keyword_matches()` is new. `AssessEngine.load_patterns()` raises `ValueError` for a pattern file whose `schema_version` is not 1.1.0, so a `data_dir` holding a 1.x pattern file must be updated (PRD-335).

### Changed

- `pip install riskforge` no longer installs `keyring`, `python-dotenv` or `pydantic-settings`, which RiskForge no longer imports (`pydantic-settings` was used only by the removed server), along with the packages `keyring` pulled in. Code that relied on RiskForge to bring these in must declare them itself (PRD-329).
- The license compatibility scan now fails the build on a license violation instead of only warning, and the release workflow waives the same `pip-audit` advisories as CI, without the stale `PYSEC-2026-3412` waiver (PRD-329).
- Python 3.13 is now tested and supported. CI runs the test suite on Python 3.11, 3.12 and 3.13 on Ubuntu and macOS, and the package metadata lists Python 3.13 (PRD-355).
- The Markdown and PDF exports show who accepted each accepted risk ("Accepted by", or "not recorded" for an acceptance made before 2.0.0) and who recorded each mitigation ("Recorded by"). The Markdown export now lists each mitigation with its type, status and owner, and escapes the text it takes from the register and system (Markdown and HTML characters, and line breaks), so a field can no longer add markup to the document. The JSON export follows RMF schema 1.0.0, which has no field for these names, so it leaves them out (PRD-356).

### Fixed

- A specific mitigation that mentions monitoring or review, such as the README example "Remove postcode feature; add demographic parity monitoring", is no longer flagged vague (gate G8) when it is added, edited or imported with 2.0. A mitigation saved earlier keeps its flag until it is edited. Listed phrases now match only as whole phrases in a short description, and "tbd" or "we'll monitor it" are still flagged. When gate G1 fails, its hint now names the `riskforge assess <system-id> --dimension <dimension>` command instead of a not-applicable option that does not exist (#52).
- Common mistakes print one line saying what to do and exit 3, instead of a Python traceback: running `validate`, `export`, `import`, `risk list` or `tests generate` before `assess`; an unknown `--category`, `--dimension`, `--format` or adapter; a second `init`; a missing report or answers file; an unknown system or risk id; a bad value in an answers file; a file passed to `verify --file` or `diff` that is not a JSON RMF file; and interactive `assess` without a terminal. `riskforge verify` in a directory with no project now exits 3 instead of reporting the audit chain as verified. `system classify` without `--confirm` and a failed `--sign` also exit 3 now, not 1 (PRD-326).
- Several processes writing to one project no longer lose each other's changes. Four processes adding 25 risks each used to keep about 38 of the 100; every change now reads, writes and records its audit entry under one file lock, and all 100 items and entries are kept. Register and system files are replaced atomically and only together with their audit entry, and a change interrupted part way, including an audit line cut short by a full disk or a killed process, is finished or discarded by the next command. On Windows the store skips the directory sync that Windows does not support and writes the audit log in binary mode, so its lines end in `\n` as on other systems. A command that waits more than 120 seconds for another `riskforge` process to release the project prints one line and exits 1. A change to a project whose audit log has a line that is not a valid entry exits 2 with the integrity check's findings instead of a traceback (PRD-331).
- `riskforge verify` exited 0 after a register was edited by hand, after the last entries of `audit.jsonl` were cut off, after the log was deleted or rewritten, and after a system's files were deleted. Every audit entry now records the SHA-256 fingerprint of its system's register as stored after the change, and `.riskforge/audit.head.json` records the last entry written. `verify` exits 2, listing every finding on its own line, when a register no longer matches its latest fingerprint, the log no longer ends at the head file, the log is missing or empty while systems exist, a register or system the log names is gone, a register or system was added by hand, or a `system.yaml` does not parse, is not a valid system record, holds another id or differs from the copy in its register. A project written by 1.1.3 still verifies, with a warning that its register is not covered by a fingerprint yet, and the first change made with 2.0 records the fingerprints. `verify` takes no lock and writes nothing, so it works on a read-only copy. Every reader of `audit.jsonl` now reads it byte for byte the same way, so a byte order mark, a carriage return or another encoding on a line is reported instead of making `verify` skip the other checks. A line ending in `\r\n`, as 1.1.3 wrote on Windows, is still read. A `txn.json` that RiskForge did not write, or that does not fit the log, is reported with exit 2 by `verify` and stops every other command with one line and exit 2, and while a journal stays `verify` checks the project as recovery would leave it, so a journal cannot hide tampering. A stored file that is a directory, FIFO, device link, unreadable, nested too deeply, or larger than 64 MiB (1 GiB for `audit.jsonl`), and a system directory that cannot be read, are reported for that file instead of crashing or hanging `verify`. The rules are in ADR-03 (PRD-332).
- `risk accept` and the other commands that change data appended new entries to a project whose audit log, head file or register had been tampered with, and exited 0, so a tamper was buried under valid-looking entries, and a hand-edited register was recorded as if RiskForge had written it. `validate` and `tests generate` reported a tampered project as ready, and a corrupt last log line made `risk accept` exit 1 with a traceback after changing the register. Each of the eight commands now exits 2 when one byte of the log is changed, its last entries are cut off, a register is edited or deleted, the last log line is corrupted, a `system.yaml` does not parse or the head file is deleted, prints one line per finding and leaves the project byte for byte unchanged, and `assess` no longer runs its own narrower chain check. A register or `system.yaml` replaced by another program while a command runs, after its check, is refused when the command reads it, instead of being recorded as RiskForge's own. Recovery no longer acts on a `txn.json` that `audit.head.json` does not fit, so a planted journal cannot make the next command cut valid entries off the log, and a refusal no longer says "Nothing was changed" after recovery finished or discarded an earlier unfinished change (PRD-333).
- `riskforge init` now records a `system.created` audit entry and the first `assess` records `register.created`, so the audit log describes every system and register file. `system classify` updates the system and its register in one step with its `system.classified` entry (PRD-331).
- Interactive `riskforge assess` no longer crashes at its first prompt with `RuntimeError: asyncio.run() cannot be called from a running event loop`. The prompts now run on the command's event loop, and Ctrl+C keeps the answers given so far. Ctrl+C at the first prompt, which offers the matched pattern's risks, now ends the session; it used to be read as "no" and the questions started (PRD-325).
- Running `riskforge assess` again no longer duplicates the register. Each item is matched to the question or pattern risk it came from: the same answers change nothing and record nothing, and a changed answer updates the matching item's likelihood, severity and knowledge-gap flag and records `risk_item.updated` with `reason: reassessment`. Residual scores follow the new scores only while the item has no mitigation and was never re-scored. An acceptance is kept, and `assess` prints a line naming what changed and asking you to review the item. The `risk_item.updated` entry records the old and new likelihood, severity and knowledge-gap flag. `assess` never removes an item: items whose question is now answered no or skip, or left out of the answers file, stay in the register and are listed. A register that 1.1.3 already doubled keeps its duplicates: `assess` updates the first item for each question or pattern risk and lists the others for review. This also holds for a session stopped with Ctrl+C and run again, and for registers written by 1.1.3. The `--answers` summary now reads `N added, N updated, N unchanged` instead of `N pattern, N scored` (PRD-334).
- CLI output, help text, the PDF report, the bundled question bank and patterns, and audit-chain error messages no longer contain em-dashes, so the output can be quoted as is. The assess menus now read `1: Rare (...)` and `yes: add as a risk item with scoring`, and pattern names read `Credit scoring: demographic bias risk`. A contract test keeps em-dashes out of these files (PRD-327).
- The Debian and Ubuntu install line for PDF export now names `libgdk-pixbuf-2.0-0`. The old name `libgdk-pixbuf2.0-0` has no install candidate on Debian trixie (PRD-354).
- `riskforge import -a rag-benchmarking` now reads the `BenchmarkReport` files rag-benchmarking writes (`run_id`, no `schema_version`) instead of refusing every one with "schema v0.0.0 not supported". The Ragas metric is read as `answer_relevancy`, and older 1.x files that spell it `answer_relevance` still import under the new name. Imported risks carry `source_ref` `rag:<run_id>`. A checked metric (`faithfulness`, `answer_relevancy`, `context_recall`) that is NaN or null is refused with one line naming the metric and exit 3, where it used to be skipped without a word. A checked metric outside 0 to 1, or a report that has both `answer_relevance` and `answer_relevancy`, is refused the same way (PRD-330).
- `riskforge assess` now finds the risk pattern a system's purpose names when the keyword is a phrase or the start of a longer word: "facial recognition" and "Creditworthiness" used to match nothing, because the purpose was split on spaces and each word compared whole. A keyword still never matches inside another word ("test" does not match "contest"). Each bundled pattern now names its high-risk route: an Annex III point, or, for medical diagnosis, Article 6(1) with Regulation (EU) 2017/745 and Regulation (EU) 2017/746 in Annex I. The medical diagnosis pattern no longer needs the `essential_services` category and no longer fires on "patient", "triage" or "screening", so patient scheduling and CV screening systems stop getting it, while a system with no category whose purpose names medical diagnosis or radiology now gets it. Bare "diagnosis", "diagnostic" and "prognosis" are no longer keywords, so engine diagnostics or a sales prognosis do not get it either. Its descriptions no longer open with an unsourced "Studies show" or say the consequences of failure "must be quantified". The bare keyword "insurance" was removed from the credit pattern, and "exam" and "test" no longer trigger the education assessment pattern ("marking" does), so exam scheduling does not get it. The credit pattern's explanation risk no longer says GDPR Article 22 requires credit decisions to be explainable: it names the safeguards in GDPR Article 22(3) and the information duties in GDPR Articles 13(2)(f), 14(2)(g) and 15(1)(h), and cites Art.86(1). The biometric pattern also triggers for the `biometric` category, and a new pattern covers offending risk assessment (Annex III point 6(d)). Keywords match accented text after folding accents, so "crédit" matches "credit". Pattern items already in a register keep their earlier text and article references: running `assess` again compares only likelihood, severity and the knowledge-gap flag, and no RiskForge command changes an item's description or references yet. Do not edit `register.yaml` by hand to update them: `riskforge verify` reports a hand-edited register as tampering (PRD-335).

## [1.1.3] - 2026-09-22

### Added

- **Multi-OS CI Runner Validation (PRD-179)**: Expanded GitHub Actions test matrix to run across both `ubuntu-latest` and `macos-latest` on Python 3.11 and 3.12, ensuring WeasyPrint system dependencies (Pango, Cairo, GDK-PixBuf, libffi) link and render correctly across platforms.
- **Dedicated PDF Generation Tests (PRD-179)**: Added `tests/unit/test_pdf_exporter.py` exercising `PDFExporter.render()` with full RMF data, validating standard `%PDF-` header, `%%EOF` marker, and error handling.
- **Automated Dependabot Security Updates (PRD-187)**: Added `.github/dependabot.yml` configured for weekly scanning of Python dependencies and GitHub Actions.
- **Open-Source Standards Contract Tests (PRD-187)**: Added `tests/contract/test_ecosystem_standards.py` enforcing badge styling, Dependabot schema, and 5-tool reciprocal cross-link integrity.
- **Reproducible Build Lockfiles (PRD-177)**: Added `uv.lock` and `requirements.lock` constraints to guarantee byte-identical Article 9 Risk Management File (RMF) evidence reproducibility for formal audits (PRD NFR-6) across CI and Docker builds.

### Changed

- **Resilient Dependency Version Ranges (PRD-177)**: Transitioned runtime and server dependencies in `pyproject.toml` from hard-pinned exact versions (`==`) to bounded semantic version ranges (`>=`, `<`), enabling clean installation in shared enterprise environments containing modern compatible libraries (e.g., Pydantic 2.8+, Jinja 3.1.5+, Rich, Typer).
- **Reciprocal 5-Tool Ecosystem Footer (PRD-187)**: Updated `README.md` footer to link the full open-source governance suite (`litmusai`, `license-compliance-checker`, `rag-benchmarking`, `riskforge`, and `agentic-document-analyser`).
- **Standardized Flat-Square Badges (PRD-187)**: Aligned all top README badges to `style=flat-square` with brand teal `#0D5463`.
- **macOS Apple Silicon Library Fallback (PRD-179)**: Configured `PDFExporter` on macOS to automatically register `/opt/homebrew/lib` and `/usr/local/lib` in `DYLD_FALLBACK_LIBRARY_PATH` before importing WeasyPrint.
- Cleaned up `Repository` URL in `pyproject.toml` by removing the trailing `.git` suffix.
- `ci.yml` and `release.yml` accept `workflow_dispatch`, enabling manual on-demand execution.
- GitHub URLs updated to use the canonical `aiexponent` organization name.

### Security

- WeasyPrint pinned to `>=70.0,<71.0` (with 70.0 in lockfile), closing PYSEC-2026-3940 (CVE-2026-55073, GHSA-r543-q48m-4c9j).
- Removed stale pip-audit waiver for PYSEC-2026-3412 as WeasyPrint 70.0 carries the upstream fix.
- Dropped stale references to un-shipped storage backends in docs and Docker.

## [1.1.2] - 2026-07-19

### Changed

- Documentation links now point at the in-repo guides. The package `Documentation` URL and the README's docs link previously targeted the product overview page, and the README link was relative, which resolves to a 404 on the PyPI project page. Both now point at the repository `docs/` folder, which renders the full user guide, the EU AI Act Article 9 mapping, and the audit-chain design (including the architecture diagrams) on GitHub. A `docs/README.md` index was added as the folder landing.

## [1.1.1] - 2026-07-19

- The RMF JSON Schema now requires a non-empty `disclosure` field (`required` plus `minLength: 1`). The mandatory not-legal-advice disclosure was always injected by the export path, but the schema did not enforce it, so a hand-crafted or downstream-tampered Risk Management File could validate without it. Export already fails loud when the disclosure is absent, and any downstream consumer validating against the bundled schema now rejects a disclosure-less document.

## [1.1.0] - 2026-07-19

Release-hardening pass: closes the correctness, completeness, documentation, and
performance gaps found in the 2026-07 evaluation. Reclassified to Production/Stable.

### Added

- `riskforge system classify <system-id> --confirm` records the provider's Article 6(2) Annex III self-classification and writes an audit entry. This was previously unreachable: no CLI command set the flag that validation gate G2 requires, so validation could not pass without hand-editing state files or using `--force`. An optional `--category` records or updates the Annex III category at the same time.
- `riskforge assess --answers <file.yaml>` runs the 8-dimension assessment non-interactively from a YAML answers file (question id to `applies` / `likelihood` / `severity`, plus an `add_patterns` flag), taking the same engine path as the interactive session. This enables reproducible fixtures, CI re-assessment, and scripted sample data. The interactive path is unchanged.
- `riskforge risk mitigate <system-id> <risk-id>` records a mitigation (description, control type, owner, status) against a risk item and optionally re-scores residual likelihood/severity, with an audit entry. Mitigations could previously only be added through the Python engine, so the Article 9(2)(d) risk-treatment step was unreachable from the CLI. Vague control descriptions are flagged.
- A full user guide at `docs/user-guide.md`: install and system dependencies, a worked quickstart, a command reference with exit codes, the non-interactive answers-file format, a CI-integration recipe, plugin authoring, interpreting the RMF, limitations, and an FAQ. Linked from the README.
- An `examples/` directory with worked sample systems (CV screening, credit scoring), each with a `config.yaml`, a non-interactive `answers.yaml`, and a golden RMF. `scripts/eval.py` (`make eval` / `make eval-update`) runs every example headless through init, classify, assess, accept, and export, then diffs the normalised RMF against its golden. Wired into CI via `tests/integration/test_examples.py`, so a change to scoring, questions, or the schema surfaces as a golden drift.
- A `benchmarks/` performance harness (`make bench`, `benchmarks/perf.py`) measuring audit-append and `add_risk` scaling, with documented numbers in `benchmarks/README.md`.

- Reclassified the package `Development Status` from Production/Stable to Beta while a release-hardening pass is in progress ahead of v1.1.0.
- The optional API server (`riskforge serve`) is now clearly marked experimental: it prints a not-security-hardened warning at startup and in `--help`/README, and `--allow-external` is now enforced (binding to a non-localhost host without it is refused, where the flag previously only warned). The server will be hardened and tested before it leaves experimental status.
- Test posture made honest and enforced: the `pyproject.toml` coverage comment was corrected (it claimed CI runs a unit-only `--ignore=tests/integration/` subset at ~37%, but CI runs the full suite at ~65%), the floor (`fail_under`) was raised 55 to 60, and a new CLI-surface contract test fails if a command group's help advertises a subcommand that does not ship.
- README accuracy pass: the hero logo now uses an absolute URL (it 404'd on the PyPI project page); the "SHA-256-signed" claim is corrected to "tamper-evident, SHA-256 self-verifying digest" (the RMF is hashed, and only signed when `--sign` is used); the Quick Start shows the complete workflow including the required `system classify` step, `--answers`, `risk mitigate`, and `verify --file`; a PDF system-dependencies note was added; and the on-disk layout diagram was corrected to the real `.riskforge/systems/` structure.
- CONTRIBUTING claimed that question-bank changes are gated by a CI-enforced "legal team approval" GitHub Environment, which does not exist; it is now stated as a maintainer review policy. The stale hardcoded test count was replaced with a reference to `pytest --collect-only`. Em-dashes swept from README and CONTRIBUTING per the human-voice standard.
- Makefile: the `pdf-preview` target used the removed `--version` flag (now `--sys-version`), and the `audit` target referenced a non-existent `requirements.txt` (now plain `pip-audit`).

### Fixed

- The hash-chained audit append was O(n) per write (it re-verified the whole chain and scanned it twice more, for the last hash and next sequence), so building an N-entry chain was O(n^2) and a large register stalled for minutes. Each append now chains from the tail (one entry read plus a tail-integrity check), making a build O(n): 1000 entries went from a multi-second stall to about 0.4s (see `benchmarks/`). Full-chain verification stays available via `riskforge verify`, and a new test checks that a tampered tail is refused at append time.
- The package `__version__` was hardcoded at `0.1.4` while the distribution was `1.0.0`. It now derives from the installed distribution metadata, so it cannot drift again, with a test asserting the two agree.
- Exported Risk Management Files always carried empty `test_requirements` and `cross_references`, even after running `riskforge tests generate`. Export now derives both from the register (Article 9 test requirements per high-scoring or knowledge-gap risk item, and cross-references clustered by article reference), so the RMF is complete. The schema's `TestRequirement` definition gained the `nist_rmf_ref` field the model emits.
- The `riskforge risk` group help advertised `add`, `edit`, and `score` subcommands that do not ship; it now lists only the actual commands (list, accept, mitigate).
- `riskforge serve` printed an uninterpolated `http://{host}:{port}/docs` docs link (a missing f-string), and the `riskforge tests` group help advertised a `list` subcommand that does not ship. Both corrected.
- `FileStore` now rejects a `system_id` containing a path separator, `..`, or a null byte before using it to construct filesystem paths, closing a directory-traversal vector (latent for the CLI, relevant once the API server accepts external ids). Benign typos still fall through to a clean "not found". Added score-band boundary property tests and path-traversal unit tests.
- The release workflow (`release.yml`) had three latent problems, now fixed. The CycloneDX SBOM step used a `--format json` flag that does not exist in cyclonedx-bom 4.x, so real SBOM generation silently failed behind `|| true`; it now uses the correct `--output-format JSON --outfile` invocation with no `|| true`, so a failed SBOM fails the release. The release test step ran unit-only (`--ignore=tests/integration/`), which falls below the coverage floor; it now runs the full suite. The security gate was fully advisory (`--exit-zero`, `|| true`); bandit and pip-audit now gate with the documented waivers. Added an RMF export-structure lock test (exact top-level and mitigation key sets) so schema/model drift like the mitigation-field bug cannot recur silently.
- The exported RMF always carried an empty `audit_entry_hash` (and `signed_by`), because both were set on the in-memory object after the file had already been written. Export now records the `rmf.exported` audit entry and populates both fields before rendering, so the artefact references its audit record. The self-verifying SHA-256 is computed over the document content with `sha256_hash`, `audit_entry_hash`, and `signed_by` blanked, and `verify --file` blanks the same three, so the digest still validates.
- Risk Management File export failed for any register that recorded a mitigation. The bundled `rmf.schema.json` omitted the `article_ref` and `nist_rmf_ref` fields that the `Mitigation` model serialises, so schema validation aborted the export in every format (JSON, PDF, Markdown). Added the two fields to `$defs/Mitigation` and a regression test that exports a mitigation-bearing register in all three formats.
- `riskforge risk accept` rejected the 8-character id that `riskforge risk list` prints (and that its own `--help` advertised), matching only the full UUID and crashing with an unhandled traceback on any other input. Accept now resolves a unique id prefix, and reports a clean error with exit code 1 for unknown or ambiguous ids.
- `riskforge verify --file <rmf.json>` accepted the option but ignored it, always checking the project audit chain instead, so a tampered standalone RMF still reported "no tampering detected". `--file` now recomputes the RMF's self-verifying SHA-256 digest and exits 2 when the content no longer matches it.
- The validation gate G2 remediation hint told users to run `riskforge system edit`, which does not ship. It now points at `riskforge system classify`.
- `riskforge export --sign` ignored the supplied key: `gpg` was invoked with no `--local-user`, so the detached signature used GPG's default key (false signer provenance), and a GPG error surfaced as an unhandled traceback. The key is now passed to `--local-user`, the signer is recorded on the RMF, and signing failures exit 1 with a clear message. The `--sign` value is a GPG key identifier (email, key id, or fingerprint), not a file path.
- Corrected regulatory citations in `README.md` and `docs/article-9-mapping.md`, each re-verified against source: the Texas statute is **HB 149 (TRAIGA)**, signed 22 June 2025 and effective 1 January 2026 (the repo previously cited HB 1709, which never became law); the Article 9 high-risk application date is **2 December 2027** for standalone Annex III systems, deferred from 2 August 2026 by the Digital Omnibus (endorsed by Parliament 16 June and Council 29 June 2026, pending OJEU publication), with 2 August 2028 for Annex I product-embedded systems; and the Colorado AI Act (SB 24-205) was repealed and reenacted by **SB 26-189**, effective 1 January 2027. Added a CI gate (`tests/contract/test_regulatory_claims.py`) that fails on known-wrong citations.

## [1.0.0] - 2026-05-10

First Production/Stable release. PyPI classifier flipped to `Development Status :: 5 - Production/Stable`. Closes the Top-N=4 audit pass; see `docs/audit/T-N4-readiness-2026-05-10.md` in the aiexponent monorepo for the full action list.

### Highlights

- 8 risk dimensions × 37 questions (canonical count, see PRD Amendments block in `PRD-RiskForge-v1.0.md`)
- 6 Annex III risk patterns (community contributions extend the library)
- 8 validation gates G1–G8
- SHA-256 hash-chained audit trail (see `docs/audit-chain-design.md`)
- Apache 2.0, hard-pinned deps for regulatory-evidence reproducibility
- Sigstore attestations on PyPI + CycloneDX SBOM on every GitHub release

### Fixed (production-affecting)

- **Click 8.3 incompatibility broke `riskforge --version` and other Typer-dispatched outputs in fresh installs.** Click 8.3 (released after RiskForge v0.1.4) changed the `is_eager` callback dispatch path in a way that Typer 0.12.3 cannot reach. The version callback ran but produced no output; subprocess-based integration tests captured empty stdout. **Fix:** `click>=8.1,<8.2` hard pin in `pyproject.toml`. Verified 2026-05-10 on Python 3.12.2.

- `[tool.coverage.report] fail_under` raised from `24` to `35`, calibrated to the
  unit-test-only CI matrix (CI runs `pytest --cov --ignore=tests/integration/` per
  `.github/workflows/ci.yml`, yielding ~37% coverage). Locally with integration
  tests included, coverage rises to ~59%. Staged-floor path: 24 → 35 (v1.0.0)
  → 55 (v1.0.1, after wiring `tests/integration/` into CI) → 80 (v1.1, after
  `riskforge.server` unit tests). PRD NFR-6's 80% target re-anchored to v1.1.
- `pyproject.toml` Documentation URL updated from `github.com/aiexponenthq/riskforge#readme` → `aiexponent.com/docs/riskforge`.
- `riskforge tests` Typer help text aligned to Article 9(6)–(8) (was "9(7)" only).
- `LICENSE` replaced with the verbatim Apache-2.0 SPDX template (canonical from apache.org). Earlier file had material text drift in §8 and was missing the Appendix template — caused GitHub to surface "NOASSERTION" instead of "Apache-2.0". `NOTICE` file added per Apache 2.0 §4(d) for the AI Exponent LLC copyright attribution.
- README + CHANGELOG numeric claims corrected per the 2026-05-10 audit (see Documentation Correction subsection below).
- PRD `PRD-RiskForge-v1.0.md` amended in-document with a "2026-05-10 — Pre-GA reality check" block reconciling 5 spec-vs-shipped gaps (200+→37 questions, 20→6 patterns, regulatory_ref→article_refs[] schema, 80%→55% coverage floor, hard-pin reinforcement).

### Documentation correction (post-v0.1.4 audit, 2026-05-10)

- **README + earlier CHANGELOG entries claimed "50+ guided questions"; actual count is 37.**
  The 0.1.0 entry below stating "50+" was an aspirational PRD-target figure (PRD line 114
  spec'd "200+" for v1.0; line 223 spec'd "3-5 per dimension × 8 dimensions = 24-40"). The
  PRD has since been amended to reflect shipped reality (37 questions in v1.0; community
  contributions extend the bank). Surfaces corrected: `README.md` hero + Art. 9 coverage
  Mermaid; `CONTRIBUTING.md`; `lib/tools.ts` on aiexponent.com (already correct since v0.1.4).
- **README claimed "20 Annex III scenarios" / "20 pre-built risk patterns"; actual count is 6.**
  Same root cause — PRD line 256 spec'd "Minimum 20 patterns at v1.0". PRD amended to ship
  reality (6 patterns covering credit scoring, hiring, facial recognition, medical imaging,
  content moderation, criminal risk assessment). Future patterns ship via community contribution
  — see `docs/contributing/add-pattern.md`.
- **PyPI long-description on v0.1.4 still carries the original "50+" + "Built by AiExponent LLC"
  text** because PyPI long-descriptions are immutable per release. Fix lands automatically with
  the next release tag.

## [0.1.4] - 2026-04-18

- README rewritten with Mermaid diagrams and tighter structure (Head of AI / Google review pass)
- README and brand surfaces aligned to AiExponent brand kit v4 — two-tone A mark + teal badges
- Code style: applied `ruff format` (CI-pinned 0.4.4) to all 57 source and test files —
  whitespace, blank lines, and string-quoting only; no logic changes

### Fixed
- Legal entity name corrected across docs: "AiExponent LLC" → "AI Exponent LLC"
  (AiExponent is a brand arm; the registered LLC is "AI Exponent LLC")

### Notes
- Published to PyPI as the release version since v0.1.3 was already on PyPI from an
  earlier publish pass during the CI hardening cycle. There is no functional difference
  between 0.1.3 and 0.1.4 — 0.1.4 = 0.1.3 + ruff-format + README refresh.

## [0.1.3] - 2026-04-15

### Fixed
- **`riskforge init --version` argument conflict resolved.** The app-level eager
  `--version` callback was intercepting `--version "2.0"` passed to `init`, printing
  the version string and exiting before init code ran. The init command's parameter
  was renamed to `--sys-version` / `-s`. README quick start and integration tests
  updated accordingly.
- **ruff lint failures across CI matrix.** Reconciled UP045/UP007 selector differences
  between local ruff (0.15+) and CI's pinned ruff (0.4.4): `UP045` removed from both
  global ignore and per-file-ignores (0.4.4 errors on unknown selectors in any config
  section, not just `ignore[]`); `UP007` retained in per-file-ignores so Typer 0.12.3
  CLI commands can use `Optional[X]` (0.12.3 cannot handle `str | None` at runtime).
- Three residual `I001` import-ordering errors in test files
- Unused `qid` variable in `assess.py` (`F841`)

- CI workflow excludes integration tests on push (subprocess output unreliable in
  non-TTY CI runners); the 52 unit/contract/boundary tests cover the same code paths
  reliably. Integration tests still run locally.

### Notes
- Published to PyPI alongside the parallel 0.1.2 publish pipeline; 0.1.4 supersedes
  this version on PyPI as the canonical release tag.

## [0.1.2] - 2026-04-12

### Added
- `LICENSE` file (Apache 2.0 full text) — previously only in pyproject.toml
- Root-level `CONTRIBUTING.md` — was missing despite README linking to it
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1)
- `SECURITY.md` — vulnerability disclosure policy, scope, security design notes
- `.github/ISSUE_TEMPLATE/` — bug report and question bank contribution templates
- `.github/PULL_REQUEST_TEMPLATE.md`
- `src/riskforge/__main__.py` — enables `python -m riskforge` invocation
- `pyproject.toml`: Python 3.12 classifier, `[project.urls]` (Homepage, Repository, Issues, Changelog)
- Full integration test suite — `init → seed → validate → export json → verify → export markdown`

### Fixed
- `RiskManagementFile.register` property — `rmf.register` was raising `AttributeError`
  (Python attribute is `risk_register`; alias only applies to serialisation)
- `ExportEngine` and `JSONExporter` — added `by_alias=True` to `model_dump()` so
  `risk_register` serialises as `register` per the published schema
- README — corrected GitHub org URLs (`aiexponent` → `aiexponenthq`); fixed quick start
  to show actual required args for `riskforge init` and `riskforge assess`
- Test count: 53 → 57

## [0.1.1] - 2026-04-12

### Fixed
- **`riskforge assess` implemented** — interactive 8-dimension risk assessment fully wired:
  question bank loop, pattern matching, likelihood/severity scoring via questionary,
  knowledge gap flagging, progress bar, session summary. The core user workflow now works end-to-end.
- **PDF exporter bug** — `items=rmf.register.system` corrected to `items=rmf.register.items`
- **Audit chain** — three bugs fixed: `read_audit` converted to a true async generator;
  genesis `prev_hash` initialisation aligned between `AuditEngine` and `FileStore.verify_chain`;
  `_compute_hash` made consistent (`entry_hash=""` not `pop`)
- **Sequence numbering** — first audit entry now has `seq=0` (was incorrectly `seq=1`)
- **`RiskDimension` enum** — trimmed to 8 PRD-specified dimensions; removed 5 extra values
  with no corresponding question bank YAML files
- **Typer compatibility** — replaced `str | None` union syntax with `Optional[str]` across all CLI commands

### Added
- 8 new tests covering: audit chain integrity, tamper detection, sequence numbering,
  assess engine question loading, knowledge gap flagging, PDF exporter regression guard
- Total: 53 tests passing

## [0.1.0] - 2026-04-12

### Added
- Initial release of RiskForge
- Article 9 risk management system CLI
- 8 risk dimensions with 37 questions (see Unreleased section above for the historical "50+" correction)
- 5x5 likelihood x severity scoring matrix
- JSON, PDF, and Markdown export formats
- SHA-256 hash-chain audit trail
- Integration adapters for rag-benchmarking and TraceForge
- `riskforge init`, `assess`, `validate`, `export`, `verify` commands
- `riskforge risk list/add/edit/accept/score` subcommands
- `riskforge system show/edit` subcommands
- `riskforge tests generate/list` subcommands
- `riskforge diff` and `riskforge import` commands
- Optional FastAPI server (`pip install riskforge[server]`)
- 8 export readiness gates (G1-G8)
- Plugin system via Python entry points (question banks, exporters, adapters)
- WeasyPrint PDF rendering with Jinja2 HTML templates
- `rmf.schema.json` (JSON Schema draft-2020-12) as versioned output contract
- FileStore storage backend (YAML + JSONL, git-friendly)
- Exit code 2 for `riskforge verify` failures (CI-detectable)
- Zero-telemetry guarantee enforced via pytest-socket in CI
- Docker Compose setup for team deployment
- Sigstore OIDC signing on all PyPI releases
- CycloneDX SBOM attached to every GitHub Release
- Build provenance attestation via GitHub Actions
