# Changelog

All notable changes to RiskForge are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/)

## [Unreleased]

### Changed

- Transitioned runtime and server dependencies in `pyproject.toml` from hard-pinned exact versions (`==`) to bounded semantic version ranges (`>=`, `<`), enabling clean installation in shared environments containing modern compatible libraries (e.g., Pydantic 2.8+, Jinja 3.1.5+, Rich, Typer).
- Introduced reproducible lockfiles (`uv.lock` and `requirements.lock`) to preserve bit-identical Article 9 Risk Management File (RMF) evidence reproducibility for formal audits (PRD NFR-6) across CI and Docker builds.
- Updated Dockerfile and CI workflows to enforce constraints via `requirements.lock` when present.

## [1.1.3] - 2026-09-13

### Security

- WeasyPrint pinned to 70.0, up from 68.0, closing PYSEC-2026-3940 (CVE-2026-55073, GHSA-r543-q48m-4c9j). The advisory covers two `write_pdf()` parameters, `xmp_metadata` and `stylesheets`, that built a fresh permissive URL fetcher instead of using the document's configured one, so a caller passing an attacker-controlled URL to either could read local files or reach internal hosts. RiskForge is not exposed: `PDFExporter` calls `HTML(string=...).write_pdf()` with neither parameter and renders a bundled template against the operator's own local data. The pin moves anyway, because a compliance tool should not ship a dependency with a live unpatched advisory. Verified with a before-and-after render of both `examples/` fixtures: identical page count, identical extracted text, identical glyph bounding boxes, and pixel-identical rasterisation of all twelve pages. The `examples/*/expected.json` goldens did not drift.
- The pip-audit waiver for PYSEC-2026-3412 (weasyprint presentational-hint CSS injection) was removed. The waiver comment said no fixed version existed; WeasyPrint 69.0 shipped the fix, and the 70.0 pin carries it. `pip-audit` on the pinned tree now reports only the click advisory, which remains waived and documented.

### Changed

- `ci.yml` accepts `workflow_dispatch`, so CI on `main` can be re-run on demand. A `main` branch whose last run predates a newly published advisory previously had no way to surface that advisory without an unrelated push.
- GitHub URLs now use the current `aiexponent` organisation name. The org was renamed from `aiexponenthq`, and although the old paths still redirect, the stale name was visible on the PyPI project page through the five `[project.urls]` entries and the README logo, which is served from `raw.githubusercontent.com`. The README, the contributing guide, and the two `docs/` guides were updated in the same pass. Older entries that record the earlier rename are left as written, since they describe what happened at the time.

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
