# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, Linear coding sessions and others) working in this repository. Human contributors should read [CONTRIBUTING.md](CONTRIBUTING.md) first. This file covers the same ground for an agent, and adds the exact commands CI runs.

If a ticket or prompt conflicts with this file, follow this file and point out the conflict in your PR.

## What RiskForge is

A Python CLI that builds an EU AI Act Article 9 risk register for one AI system and exports it as a hashed, schema-validated Risk Management File (JSON, PDF or Markdown). All state lives on disk under `<project>/.riskforge/`. Every change to a register is recorded in an append-only, SHA-256 hash-chained audit log.

The output goes to auditors and regulators. Accuracy and reproducibility matter more than speed or new features.

## Setup

Python 3.11, 3.12 or 3.13.

```bash
make dev-setup        # installs .[dev] (using requirements.lock when present) and the pre-commit hooks
```

Without `make`:

```bash
pip install -c requirements.lock -e ".[dev]"
```

PDF export needs WeasyPrint's system libraries. On Debian or Ubuntu:

```bash
sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
  libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info
```

## Before you open a pull request

Run every command below and make sure each one passes. They are the required checks on `main`, and GitHub blocks the merge while any of them is red. Do not report a task as done until you have seen them pass.

```bash
pip install ruff==0.4.4             # CI pins this version, newer ruff can disagree
ruff check src/ tests/              # CI job: Lint & Format
ruff format --check src/ tests/     # CI job: Lint & Format
pytest --cov                        # CI job: Test (full suite, fails under 60% coverage)
pytest tests/boundary/ -v           # CI job: Import Boundary Enforcement (ADR-02)
bandit -ll -r src/                  # CI job: Security Scan
```

`make format` fixes most lint and format failures. `make lint` runs both ruff checks. The Security Scan job also runs `pip-audit` with two documented waivers. If you change dependencies, run it with the same flags as `.github/workflows/ci.yml`.

## Tests

| Folder | What goes there |
|---|---|
| `tests/unit/` | Pure functions, models and engine logic |
| `tests/integration/` | CLI flows end to end, including the golden examples |
| `tests/contract/` | Schema validation and repository standards |
| `tests/boundary/` | Import boundary enforcement |

Rules that trip agents:

- **Sockets are disabled.** `pytest` runs with `--disable-socket`. Any test that runs a CLI command or calls `asyncio.run()` needs `@pytest.mark.enable_socket`, because the event loop opens a local socket pair. See `tests/unit/test_cli_verify_output.py` for the pattern.
- **Markers are strict.** `--strict-markers` is on, so an unregistered marker fails the run.
- **Golden files.** `tests/integration/test_examples.py` compares every example in `examples/*/` with its committed `expected.json`. If your change alters export content on purpose (including the version string in the disclosure), run `make eval-update` and check that the golden diff shows only the change you intended.
- **Every bug fix gets a test that fails without the fix.** Confirm it fails by reverting the fix locally before you open the pull request.
- Test CLI commands with Typer's `CliRunner` and a `tmp_path` project directory.

## Architecture rules

```
cli/       thin Typer commands: parse input, call the engine, print with rich
engine/    all business logic, never imports cli
storage/   FileStore and the StorageBackend interface
models/    Pydantic v2 models
exporters/ JSON, PDF and Markdown exporters, loaded through entry points
```

- `riskforge.engine` must not import `riskforge.cli`. `tests/boundary/test_import_boundaries.py` enforces this. Engine code takes configuration as constructor arguments and does not read environment variables. See [docs/adr/ADR-02-import-boundaries.md](docs/adr/ADR-02-import-boundaries.md).
- Keep business logic out of CLI commands.
- Every change to a register goes through `RiskEngine`, which writes the register and then records an audit event through `AuditEngine.record()`. Never write `register.yaml` or `audit.jsonl` directly, and never edit or reorder existing audit entries.

## Hard rules

1. **No network calls and no telemetry.** RiskForge never calls home. Do not add code that sends data anywhere unless the user explicitly configures a destination. This applies to dependencies too.
2. **Exports must be reproducible.** The same register must produce the same export content. Do not add timestamps, random values, dictionary-order effects or environment-dependent text to export content. The existing `id` and `generated_at` fields of the Risk Management File are known exceptions. Adding more is a bug.
3. **The question bank is the source of truth.** Questions live in `src/riskforge/_data/question_bank/*.yaml` and patterns in `src/riskforge/_data/patterns/patterns.yaml`. Never hardcode questions in Python. Leave these files alone unless the ticket asks for a change. When it does, flag it at the top of the PR description so a maintainer can arrange a regulatory review.
4. **Regulatory references must be exact.** Any EU AI Act reference in code, docstrings, output or docs must name the exact article or annex, for example `Art.9(2)(a)`. Never write a regulatory date, deadline or paraphrase of the law from memory. If a change needs one and you cannot check it against the official text, stop and raise it in the PR rather than guess.
5. **Do not change the hashing.** The audit chain hash, the export SHA-256 and the fields blanked before hashing (`sha256_hash`, `audit_entry_hash`, `signed_by`) must stay compatible with `riskforge verify`. Changing any of them needs an ADR in `docs/adr/` first.
6. **No secrets in the repository.** Never commit keys, tokens or `.env` files, and never print secrets in output or logs.
7. **Dependencies must be Apache-2.0 compatible.** Use bounded version ranges (`>=x,<y`) in `pyproject.toml`, then run `make lock` to refresh `uv.lock` and `requirements.lock`.

## Code style

- Pydantic v2 only, with no v1 patterns.
- In `src/riskforge/cli/commands/`, use `Optional[X]`, not `X | None`. Typer 0.12.3 fails on the union syntax, and the ruff config ignores `UP007` there for this reason.
- Catch specific exceptions. No bare `except:`, and do not swallow errors.
- CLI output goes through `rich`. Exit code 2 means "integrity failure" (`verify`, a corrupt audit chain), and CI pipelines depend on that.
- Comment only where the reason is not obvious from the code.
- **No em-dashes (—) in anything a user sees**: CLI output, help text you add, docs, README or CHANGELOG. The aiexponent.com content check rejects them, and the site records this CLI's output. Use a colon, comma or full stop instead.

## Git and pull requests

- Branch from the latest `main`. Name the branch `<type>/<area>-<purpose>`, for example `fix/cli-verify-emdash`. Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `hotfix`. Some platforms only allow pushing to a branch name they generate. In that case keep their branch and mention it in the PR.
- One piece of work per branch and per pull request.
- Use conventional commits, and start the pull request title the same way: `fix(cli): ...`, `feat(engine): ...`, `docs: ...`.
- **Do not add `Co-authored-by` lines or any other attribution for AI agents or bots** to commits. Commits name the human owner only. When a platform adds one automatically, mention it in the PR so the maintainer can strip it at merge time.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for any change a user would notice.
- Never force-push `main`, never skip hooks with `--no-verify`, and never push tags. Tagging a version publishes to PyPI and is done by a maintainer only.
- Keep internal planning documents (`PRD-*`, `HLD-*`, `LLD-*`, `*-spec.md`, roadmaps) out of this public repository.

## Releases (maintainers only)

The package version lives in `pyproject.toml`, and `riskforge.__version__` reads it from package metadata. A release bumps `pyproject.toml`, moves the `[Unreleased]` CHANGELOG entries under the new version, runs `make eval-update` (the version string is part of every golden file), and pushes a `vX.Y.Z` tag, which runs `.github/workflows/release.yml`. Agents prepare the bump in a pull request but do not tag.

## Pull request description

Include:

- What changed and why, in two or three sentences.
- The commands from "Before you open a pull request" that you ran, and their result.
- For a bug fix: the test that fails without the fix.
- Anything you were unsure about or did not do.
