# Contributing to RiskForge

Thank you for your interest in contributing. RiskForge is an open-source EU AI Act Article 9 risk management tool built by [AI Exponent LLC](https://aiexponent.com).

---

## Where to Start

**The easiest contribution requires zero Python.** The two highest-value contributions are:

1. **Add a question** to an existing risk dimension, edit one YAML file, open a PR.
2. **Add a risk pattern** for a new Annex III use case, add a YAML block, open a PR.

Both paths are documented in detail in [`docs/contributing/`](docs/contributing/).

---

## Development Setup

```bash
git clone https://github.com/aiexponent/riskforge
cd riskforge
make dev-setup      # pip install -e ".[dev]" + pre-commit install
make test           # run the full test suite (all tests must pass; run `pytest --collect-only -q` for the current count)
make lint           # ruff check + format
```

Requirements: Python 3.11+, Git.

### Dependency Management: Resilient Ranges & Reproducible Lockfiles

Runtime dependencies in `pyproject.toml` use bounded semantic version ranges (`>=`, `<`) rather than hard-pinned exact versions (`==`). This ensures enterprise users can seamlessly install `riskforge` in shared environments without package conflicts (e.g., compatible Pydantic 2.8+, Jinja 3.1.5+, Rich, or Typer).

To maintain strict regulatory evidence stability (PRD NFR-6) — ensuring an Article 9 Risk Management File (RMF) generated in May is byte-identical to one generated in August for the same inputs — builds are locked and validated via lockfiles (`uv.lock` and `requirements.lock`):
- `uv.lock` provides cross-platform locked dependency resolution for `uv` workflows.
- `requirements.lock` provides pip-compatible constraints used by CI and Docker builds.

When upgrading dependencies:

1. Update the range in `pyproject.toml` if needed, then re-lock via `make lock` (or `uv lock && uv export --frozen --no-dev -o requirements.lock`).
2. Run the test and evaluation suites (`make test && make eval`) to confirm no breaking behavioral drift.
3. Verify CI is green.
4. Add a CHANGELOG line under `[Unreleased]` naming the dependency change and the rationale.

---

## Contribution Paths

### 1. Add a question (no Python required)

Edit `src/riskforge/_data/question_bank/<dimension>.yaml` and add a question block:

```yaml
- id: HS-008
  text: "Could the system's output be used to deny access to healthcare or emergency services?"
  guidance: "Consider both direct decisions and inputs to downstream human decisions."
  annex_iii_categories: [essential_services, critical_infrastructure]
  default_likelihood_hint: 2
  default_severity_hint: 5
  article_refs: ["Art.9(2)(a)", "Art.9(9)"]
  nist_rmf_ref: "MAP 1.5"
  iso42001_ref: "Clause 6.1"
  regulatory_status: settled  # or pending_implementing_act
```

Run `make test` to verify the YAML is valid. See full guide: [`docs/contributing/add-question.md`](docs/contributing/add-question.md).

**Note:** Question-bank changes carry regulatory weight. Flag them clearly in your PR so a maintainer can arrange an EU AI Act counsel review before merge. This is a maintainer review policy, not an automated CI gate.

### 2. Add a risk pattern (no Python required)

Add a YAML block to `src/riskforge/_data/patterns/patterns.yaml`:

```yaml
- pattern_id: MY_PATTERN
  name: "Use Case, Key Risk"
  description: "Brief description of why this pattern matters."
  triggers:
    annex_iii_categories: [employment]
    purpose_keywords: [screening, hiring, recruitment]
  risks:
    - dimension: discrimination
      title: "Risk title (max 120 chars)"
      description: "What could go wrong and why."
      likelihood_hint: 3
      severity_hint: 4
      article_refs: ["Art.9(2)(a)"]
      nist_rmf_ref: "MEASURE 2.9"
      iso42001_ref: "Clause A.7"
```

See full guide: [`docs/contributing/add-pattern.md`](docs/contributing/add-pattern.md).

### 3. Add a new exporter (Python)

Implement the `Exporter` ABC and register via entry point. See [`docs/contributing/add-exporter.md`](docs/contributing/add-exporter.md).

### 4. Fix a bug or add a feature

1. Open an issue first to discuss the change
2. Fork the repository
3. Create a branch: `git checkout -b fix/short-description`
4. Write a test that covers the change
5. Implement the change
6. Run `make test`, all tests must pass, no new failures (`pytest --collect-only -q | tail -1` reports the canonical count for the version on `main`)
7. Run `make lint`, no ruff errors
8. Open a pull request against `main`

---

## Architecture

RiskForge has four strictly-decoupled layers. **Never import across boundaries:**

```
CLI (riskforge/cli/):       thin commands; calls engine functions only
Engine (riskforge/engine/): all business logic; no CLI/server imports
Storage (riskforge/storage/): FileStore and StorageBackend ABC
Server (riskforge/server/): optional FastAPI; never imported by CLI
```

The CI pipeline enforces this with AST-based import boundary tests (ADR-02).

Key rule: if your change adds a `from riskforge.cli import ...` in engine code, the CI will fail.

---

## Tests

- Unit tests: `tests/unit/`, fast, no I/O
- Contract tests: `tests/contract/`, JSON schema validation
- Boundary tests: `tests/boundary/`, import enforcement
- Integration tests: `tests/integration/`, end-to-end CLI pipeline

All tests must pass before merge. New features must include tests.

```bash
make test                           # full suite
pytest tests/unit/ -q               # unit only
pytest tests/contract/ -q           # schema contracts only
pytest -k "test_audit" -q           # run specific tests
```

---

## Commit Messages

Use conventional commits:

```
fix: correct PDF exporter context variable (items not system)
feat: add --dimension flag to riskforge assess
test: add audit chain tamper detection test
docs: add CODE_OF_CONDUCT.md
chore: bump version to 0.1.2
```

---

## Pull Request Review Criteria

- All CI checks pass (lint, test, schema-validate, boundary, security)
- Test coverage not reduced
- No business logic in CLI commands
- No imports across layer boundaries
- CHANGELOG.md updated

---

## Legal

By contributing, you agree that your contributions are licensed under the Apache 2.0 License.

Questions? Open a GitHub Issue or email `hello@aiexponent.com`.
