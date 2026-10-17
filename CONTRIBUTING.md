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

Requirements: Python 3.11, 3.12 or 3.13, Git.

### Dependency Management: Resilient Ranges & Reproducible Lockfiles

Runtime dependencies in `pyproject.toml` use bounded version ranges (`>=`, `<`) rather than exact pins (`==`), so `riskforge` installs next to other packages that need compatible versions of Pydantic, Jinja, Rich, or Typer.

Lockfiles pin the exact versions that CI installs, so a new dependency release cannot change RiskForge's behavior without a reviewed lockfile change (`uv.lock` and `requirements.lock`):
- `uv.lock` provides cross-platform locked dependency resolution for `uv` workflows.
- `requirements.lock` provides pip-compatible constraints used by CI.

When upgrading dependencies:

1. Update the range in `pyproject.toml` if needed, then re-lock via `make lock` (or `uv lock && uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.lock`).
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
  article_refs: ["Art.9(2)(a)"]
  nist_rmf_ref: "MAP 5.1"
  iso42001_ref: "Clause 6.1"
  regulatory_status: settled  # or pending_implementing_act
```

No test checks the question's fields, so compare them with an existing question; `make test` fails if the question cites an article that is not on the checked list in `tests/contract/legal_references.yaml`. See full guide: [`docs/contributing/add-question.md`](docs/contributing/add-question.md).

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
      nist_rmf_ref: "MEASURE 2.11"
      iso42001_ref: "Annex A.7"
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

RiskForge has three layers:

```
CLI (riskforge/cli/):       thin commands; calls engine functions only
Engine (riskforge/engine/): all business logic; no CLI imports
Storage (riskforge/storage/): FileStore and StorageBackend ABC
```

CI enforces one boundary (ADR-02): the engine must not import the CLI. If your change adds a `from riskforge.cli import ...` in engine code, the boundary tests fail. Keep the other layers apart by convention: CLI commands call the engine, and the engine reads and writes project state through the storage backend.

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
