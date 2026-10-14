"""One integrity check for the whole project (ADR-03 section 5).

``check_integrity`` is the only verification path: ``riskforge verify`` runs it, and
commands that change or export data run it first through ``require_intact``. It reads
only, reports every finding, and never raises for a file that does not parse.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from riskforge.engine.audit import BASELINE_EVENT
from riskforge.integrity.canonical import UnfingerprintableDocumentError, document_fingerprint
from riskforge.models.audit import AuditEntry
from riskforge.models.system import AISystem
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import (
    AuditLogCorruptError,
    RegisterNotFoundError,
    StoredFileCorruptError,
)

# Events that change a register. A system whose log holds one must have a register.
REGISTER_EVENT_PREFIXES = ("register.", "risk_item.", "mitigation.")
REGISTER_EVENTS = frozenset({"risk.accepted"})

# Events only RiskForge 2.0 and later write (ADR-03 section 7). A log holding one was
# kept with a head file, as is a log holding a fingerprint.
EVENTS_SINCE_2_0 = frozenset({"system.created", "register.created", BASELINE_EVENT})

UNENCODABLE = (
    "it holds a value canonical JSON cannot encode (an unquoted date or timestamp, "
    "!!binary, !!set or mixed key types)"
)


@dataclass(frozen=True)
class IntegrityReport:
    """Every finding of one check. ``ok`` is True when there are no errors."""

    errors: list[str]
    warnings: list[str] = field(default_factory=list)
    entries: list[AuditEntry] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def head(self) -> AuditEntry | None:
        return self.entries[-1] if self.entries else None


class IntegrityError(RuntimeError):
    """The project failed its integrity check. ``report`` holds every finding."""

    def __init__(self, report: IntegrityReport) -> None:
        super().__init__(" ".join(report.errors))
        self.report = report


class ChangeInProgressError(RuntimeError):
    """A writer was busy for every attempt of a check, so nothing could be concluded."""


def latest_fingerprints(entries: list[AuditEntry]) -> dict[str, str]:
    """The last ``register_fingerprint`` the log records for each system."""
    latest: dict[str, str] = {}
    for entry in entries:
        if entry.register_fingerprint is not None:
            latest[entry.system_id] = entry.register_fingerprint
    return latest


def _changes_register(entry: AuditEntry) -> bool:
    if entry.register_fingerprint is not None:
        return True
    if entry.event == BASELINE_EVENT:  # a baseline of a system that had no register
        return False
    return entry.event.startswith(REGISTER_EVENT_PREFIXES) or entry.event in REGISTER_EVENTS


@dataclass
class _Register:
    """A system's stored register as the check sees it."""

    exists: bool = False
    document: Any = None
    fingerprint: str | None = None
    problem: str | None = None  # why it cannot be fingerprinted

    @property
    def holds_items(self) -> bool:
        if self.problem is not None:
            return True  # unknown, so it cannot count as empty
        return isinstance(self.document, dict) and bool(self.document.get("items"))


async def _read_register(storage: StorageBackend, system_id: str) -> _Register:
    try:
        document = await storage.read_register_document(system_id)
    except RegisterNotFoundError:
        return _Register()
    except StoredFileCorruptError:
        return _Register(exists=True, problem="it does not parse as YAML")
    try:
        return _Register(exists=True, document=document, fingerprint=document_fingerprint(document))
    except UnfingerprintableDocumentError:
        return _Register(exists=True, document=document, problem=UNENCODABLE)


def _head_findings(head: dict | None, head_present: bool, entries: list[AuditEntry]) -> list[str]:
    if not head_present:
        if any(
            entry.register_fingerprint is not None or entry.event in EVENTS_SINCE_2_0
            for entry in entries
        ):
            return [
                "The head file .riskforge/audit.head.json is missing, but the audit log holds "
                "entries written by RiskForge 2.0 or later."
            ]
        return []
    if head is None:  # present but unreadable, already reported
        return []
    if not entries:
        return [
            f"audit.head.json records seq {head['seq']}, but the audit log is missing or empty."
        ]
    last = entries[-1]
    if last.seq < head["seq"]:
        return [
            f"The audit log ends at seq {last.seq}, but audit.head.json records seq "
            f"{head['seq']}: entries were removed from the end."
        ]
    if last.seq > head["seq"]:
        return [
            f"The audit log has entries after seq {head['seq']} that RiskForge did not "
            f"record (last seq {last.seq})."
        ]
    if last.entry_hash != head["entry_hash"]:
        return [f"Entry seq {last.seq} does not match audit.head.json: the log was rewritten."]
    return []


_ABSENT = object()


def _value(value: Any) -> str:
    return "absent" if value is _ABSENT else repr(value)


def _system_copy_differences(stored: dict, embedded: Any) -> str:
    if not isinstance(embedded, dict):
        return "register.yaml holds no system mapping"
    parts = []
    for key in sorted(set(stored) | set(embedded), key=str):
        ours, theirs = stored.get(key, _ABSENT), embedded.get(key, _ABSENT)
        if ours != theirs:
            parts.append(
                f"{key} is {_value(ours)} in system.yaml and {_value(theirs)} in register.yaml"
            )
    return "; ".join(parts)


async def _system_findings(
    storage: StorageBackend, system_id: str, register: _Register
) -> list[str]:
    prefix = f"System {system_id}: system.yaml"
    try:
        document = await storage.read_system_document(system_id)
    except StoredFileCorruptError:
        return [f"{prefix} does not parse as YAML."]
    try:
        system = AISystem.model_validate(document)
    except ValidationError as exc:
        return [f"{prefix} is not a valid system record ({exc.error_count()} field error(s))."]
    if str(system.id) != system_id:
        return [f"{prefix} holds id {system.id}, not the id of its directory."]
    if register.exists and register.problem is None and isinstance(register.document, dict):
        differences = _system_copy_differences(document, register.document.get("system"))
        if differences:
            return [f"{prefix} differs from the copy in register.yaml: {differences}."]
    return []


def _register_findings(
    system_id: str,
    register: _Register,
    latest: dict[str, str],
    head_present: bool,
    changed: set[str],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    name = f"System {system_id}: register.yaml"
    if not register.exists:
        if system_id in changed:
            errors.append(f"{name} is missing, but the audit log records changes to it.")
    elif system_id in latest:
        if register.problem is not None or register.fingerprint != latest[system_id]:
            reason = f" ({register.problem})" if register.problem else ""
            errors.append(
                f"{name} was changed outside RiskForge: it does not match the fingerprint "
                f"the audit log recorded last{reason}."
            )
    elif register.problem is not None:
        errors.append(f"{name} cannot be fingerprinted: {register.problem}.")
    elif head_present:
        errors.append(
            f"{name} has no fingerprint in the audit log, so it was added or replaced "
            "outside RiskForge."
        )
    else:
        warnings.append(
            f"{name} is not covered by a fingerprint yet (last written before RiskForge 2.0). "
            "The next change records one."
        )
    return errors, warnings


async def check_integrity(storage: StorageBackend) -> IntegrityReport:
    """Check the chain, the head file, every register and system file, and the files on disk.

    Reads only. Reports every finding of ADR-03 section 5 rather than stopping at the
    first, and reports a file that does not parse as a finding instead of raising.
    """
    _chain_ok, chain_errors = await storage.verify_chain()
    errors: list[str] = list(chain_errors)
    warnings: list[str] = []
    try:
        entries = [entry async for entry in storage.read_audit()]
        log_readable = True
    except AuditLogCorruptError:  # verify_chain already named the line
        entries, log_readable = [], False

    head: dict | None = None
    try:
        head = await storage.read_audit_head()
        head_present = head is not None
    except StoredFileCorruptError as exc:
        errors.append(str(exc))
        head_present = True

    systems = await storage.list_systems()
    registers = {system_id: await _read_register(storage, system_id) for system_id in systems}
    for system_id in systems:
        errors.extend(await _system_findings(storage, system_id, registers[system_id]))

    if not log_readable:
        return IntegrityReport(errors=errors, warnings=warnings, entries=[])

    errors.extend(_head_findings(head, head_present, entries))

    if systems and not entries:
        with_items = [sid for sid in systems if registers[sid].holds_items]
        if head_present or with_items:
            files = [f"systems/{sid}/register.yaml" for sid in with_items]
            if head_present:
                files.append("audit.head.json")
            errors.append(
                "The audit log is missing or empty, but the project has files it should "
                f"record: {', '.join(files)} (under .riskforge/)."
            )
        else:
            warnings.append(
                "The audit log holds no entries and no register holds risks yet (a project "
                "last changed by RiskForge 1.1). The next change records a baseline."
            )
        return IntegrityReport(errors=errors, warnings=warnings, entries=entries)

    latest = latest_fingerprints(entries)
    changed = {entry.system_id for entry in entries if _changes_register(entry)}
    for system_id in systems:
        found, noted = _register_findings(
            system_id, registers[system_id], latest, head_present, changed
        )
        errors.extend(found)
        warnings.extend(noted)

    named = {entry.system_id for entry in entries if entry.system_id}
    for system_id in sorted(named - set(systems)):
        errors.append(f"System {system_id} appears in the audit log, but its files are missing.")
    if head_present:
        for system_id in systems:
            if system_id not in named:
                errors.append(
                    f"System {system_id}: no audit entry names it, so it was added outside "
                    "RiskForge."
                )
    return IntegrityReport(errors=errors, warnings=warnings, entries=entries)


async def require_intact(storage: StorageBackend) -> IntegrityReport:
    """The report of an intact project, or ``IntegrityError`` holding every finding."""
    report = await check_integrity(storage)
    if not report.ok:
        raise IntegrityError(report)
    return report


async def check_integrity_settled(
    storage: StorageBackend, *, repeats: int = 3, pause: float = 0.25
) -> IntegrityReport:
    """Run ``check_integrity`` without the write lock, as ``riskforge verify`` does.

    The commit markers (the journal and the head) are read before and after each
    check. If either moved, or a journal is present, a writer was busy, so the check
    is repeated up to ``repeats`` times (ADR-03 section 5).

    Raises
    ------
    ChangeInProgressError
        If a writer was busy for every attempt.
    """
    for attempt in range(repeats + 1):
        if attempt:
            await asyncio.sleep(pause)
        before = await storage.read_commit_markers()
        if before[0] is not None:
            continue
        try:
            report = await check_integrity(storage)
        except OSError:
            # A file a writer renamed or removed while it was read. Only a moved
            # marker excuses it; otherwise it is a real error and is raised.
            if await storage.read_commit_markers() == before:
                raise
            continue
        if await storage.read_commit_markers() == before:
            return report
    raise ChangeInProgressError(
        "A change to this project is in progress or unfinished (.riskforge/txn.json), so "
        "it was not checked. Run verify again when it has finished; if no riskforge command "
        "is running, the next command that changes the project finishes or discards it."
    )
