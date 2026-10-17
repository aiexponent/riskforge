# ADR-02: Strict Import Boundary Between CLI, Engine, and Server

**Status:** Accepted
**Date:** April 2026
**Deciders:** System Architect, Infrastructure Engineer

## Context

RiskForge has three major layers: CLI (Typer), Engine (business logic), and Server (FastAPI). Without explicit enforcement, Python imports can become circular or drag unintended dependencies into lightweight install targets.

## Decision

The engine layer has zero imports from CLI or server. The server has zero imports from CLI. This is enforced by automated boundary tests in CI (`tests/boundary/test_import_boundaries.py`).

## Rationale

- **CLI install target must stay lightweight.** `pip install riskforge` must not drag in FastAPI, uvicorn, and all server dependencies. The 15MB target requires strict separation.
- **Engine testability.** The engine must be independently unit-testable without a running CLI or server.
- **Dependency isolation.** Server can be upgraded (FastAPI version bumps) without touching the engine or CLI.

## Enforcement

`tests/boundary/test_import_boundaries.py` uses `ast.parse()` to statically verify that `riskforge.engine.*` source files contain no `import riskforge.cli` statements. This runs in CI on every PR.

## Consequence

Engine code that needs information from configuration must accept it as constructor arguments. No environment variable reads in engine modules: those happen in the CLI and are passed in.

## Update (2.0.0)

The experimental server layer and its optional install extra were removed in 2.0.0 (PRD-354). The rule that the engine never imports the CLI still applies, and the boundary test now checks only that rule.
