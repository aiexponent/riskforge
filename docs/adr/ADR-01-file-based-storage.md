# ADR-01: File-Based Storage as OSS Tier Default

**Status:** Accepted
**Date:** April 2026
**Deciders:** System Architect, Infrastructure Engineer

## Context

RiskForge needs a storage mechanism for project state (system metadata, risk register, audit log). Options considered: SQLite, PostgreSQL, YAML + JSONL files.

## Decision

Project state lives in `.riskforge/` (YAML + JSONL files). Not SQLite. Not PostgreSQL.

## Rationale

- **Git-diff-friendly.** A compliance team can review a PR that modifies a risk register, reading the YAML diff in GitHub. A SQLite binary blob is opaque.
- **Regulator-readable.** A competent authority can read `register.yaml` and `audit.jsonl` with a text editor, which shows the changes; checking the hashes needs the script in docs/audit-chain-design.md section 5.2 (Python and PyYAML, no RiskForge installation).
- **Reviewable.** A change to a register shows up as a readable YAML diff. Merging two branches that both changed `.riskforge/` is not supported: the merged audit log is no longer one chain, and `riskforge verify` exits 2.
- **Few dependencies.** The FileStore uses PyYAML, filelock, Pydantic and the standard library.

## Trade-offs Accepted

Since 2.0.0, writers on one machine are serialized by a file lock, and each change is committed together with its audit entry through `StorageBackend.unit_of_work()`. Several people editing one project from different machines or git branches is not supported. The `StorageBackend` ABC leaves room for a backend that supports it (for example a relational database); none ships in this package.

## Enforcement

The `StorageBackend` ABC defines the interface. All storage implementations must conform to the async method signatures. FileStore is the only backend that ships today; the ABC exists so a future backend can be added without changing the engine.
