"""FileStore: OSS storage backend using YAML + JSONL files.

All data is persisted under ``<project_dir>/.riskforge/`` using a combination
of YAML files (human-readable, diffable) and JSONL for the append-only audit
log.

Directory layout
----------------
::

    <project_dir>/
    ├── riskforge.yaml          chmod 600  # project manifest
    └── .riskforge/             chmod 700
        ├── audit.jsonl         chmod 600  # append-only audit chain
        ├── audit.head.json                # seq and hash of the last entry written
        ├── audit.lock                     # serialises writers across processes
        ├── txn.json                       # journal, only while a commit is in flight
        ├── .nodelete                      # sentinel preventing accidental deletion
        └── systems/
            └── <system_id>/
                ├── system.yaml
                ├── register.yaml
                └── mitigations.yaml       # derived catalogue, never read back

Writes
------
Every file is replaced atomically (temp file, fsync, rename), so a reader sees
the old file or the new one, never a mix. Inside ``unit_of_work()``, register
and system writes are staged as ``<name>.pending`` and renamed into place only
after the audit entry that records them is appended. A journal (``txn.json``)
written before the append records the log length, so the next unit of work can
finish a change whose entry reached the log in full, or cut off a torn append and
discard the change.

Read-only mode
--------------
``FileStore(project_dir, read_only=True)`` reads without taking the lock or writing
any file, so ``riskforge verify`` works on a read-only copy or an archive mount.
Every write raises ``PermissionError``, and ``unit_of_work()`` raises
``PendingChangeError`` while a journal shows a change that is not finished.

Security model
--------------
- The ``.riskforge`` directory and all files within it are created with
  restrictive permissions (700 / 600) to prevent other local users from
  reading sensitive risk data.
- A ``.nodelete`` sentinel file inside ``.riskforge/`` guards against
  accidental ``rm -rf`` of the project root.
- If the project root is inside a git repository and ``riskforge.yaml``
  would be tracked, a warning is emitted; callers should add
  ``.riskforge/`` to ``.gitignore``.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import errno
import json
import logging
import os
import stat
import subprocess
import tempfile
import warnings
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock, Timeout
from pydantic import ValidationError

from riskforge.integrity.chain import (
    BASELINE_EVENT,
    entry_to_dict,
    verify_links,
    written_since_2_0,
)
from riskforge.integrity.strict_json import StrictJsonError, refuse_deep_nesting
from riskforge.models.audit import AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.system import AISystem
from riskforge.storage.base import (
    RECOVERED_STATE_KEY,
    WRITTEN_STATE_KEY,
    PendingChange,
    StorageBackend,
)
from riskforge.storage.errors import (
    AuditLogCorruptError,
    InvalidSystemIdError,
    ManifestMissingError,
    PendingChangeError,
    ProjectExistsError,
    ProjectLockedError,
    ProjectNotFoundError,
    RegisterNotFoundError,
    StoredFileCorruptError,
    SystemNotFoundError,
)

logger = logging.getLogger(__name__)

SENTINEL = ".nodelete"
PENDING_SUFFIX = ".pending"
DEFAULT_LOCK_TIMEOUT = 120.0
_LOCK_POLL_SECONDS = 0.02


class _Scope:
    """The writes staged by one open unit of work, as paths relative to ``.riskforge``."""

    def __init__(self) -> None:
        self.staged: list[str] = []
        self.state: dict[str, Any] = {}


# Open units of work in the current context, keyed by the resolved .riskforge path, so
# two FileStore objects for one project join the same scope instead of waiting on each other.
_ACTIVE_UOW: contextvars.ContextVar[dict[str, _Scope] | None] = contextvars.ContextVar(
    "riskforge_filestore_uow", default=None
)


# Windows cannot open a directory with os.open, and opens file descriptors in text mode
# unless O_BINARY is passed, which would turn each "\n" written into "\r\n".
_IS_WINDOWS = os.name == "nt"
_O_BINARY = getattr(os, "O_BINARY", 0)


def _fsync_dir(directory: Path) -> None:
    if _IS_WINDOWS:
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` so readers see the old or the new file, never a mix."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _pending(path: Path) -> Path:
    return path.with_name(path.name + PENDING_SUFFIX)


def _first_line(exc: BaseException) -> str:
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


# Largest stored file RiskForge reads. A larger register, system file, journal or head
# file, or a larger audit log, is reported instead of being read into memory.
MAX_STORED_FILE_BYTES = 64 * 1024 * 1024
MAX_AUDIT_LOG_BYTES = 1024 * 1024 * 1024
# Most entries one commit appends (its own and the baseline of every other system).
MAX_ENTRIES_PER_COMMIT = 10_000

_BYTE_ORDER_MARKS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
_JOURNAL_FILES = frozenset({"system.yaml", "register.yaml", "mitigations.yaml"})


def _read_stored(path: Path, label: str, limit: int = MAX_STORED_FILE_BYTES) -> bytes:
    """The bytes of a stored file, read only if it is a regular file of at most ``limit``.

    The file is opened without blocking and checked through its descriptor, so a FIFO,
    a device or a symlink to one is refused without being read, and a file swapped in
    after a check cannot slip past it.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    StoredFileCorruptError
        If it is not a regular file, is too large or cannot be read.
    """
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | _O_BINARY)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise StoredFileCorruptError(f"{label} cannot be read: {exc.strerror or exc}.") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise StoredFileCorruptError(f"{label} is not a regular file.")
        too_large = StoredFileCorruptError(f"{label} is larger than {limit // (1024 * 1024)} MiB.")
        if info.st_size > limit:
            raise too_large
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(fd, 1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise too_large
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise StoredFileCorruptError(f"{label} cannot be read: {exc.strerror or exc}.") from exc
    finally:
        os.close(fd)


def _load_yaml(data: bytes, label: str) -> object:
    """``yaml.safe_load`` of stored bytes; a file that does not parse raises a typed error."""
    try:
        return yaml.safe_load(data)
    except yaml.YAMLError as exc:
        detail = " ".join(str(exc).split())
        raise StoredFileCorruptError(f"{label} does not parse as YAML: {detail}") from exc
    except RecursionError as exc:
        raise StoredFileCorruptError(f"{label} does not parse: it is nested too deeply.") from exc


def _settle_outcome(journal: dict, tail: bytes) -> tuple[str, list[AuditEntry]]:
    """What recovery does with the bytes an interrupted commit left after ``log_size``.

    ``("forward", entries)``: exactly ``count`` complete lines hold the entries
    ``after_seq + 1`` to ``after_seq + count``, the first being the change's own and any
    others ``register.baselined``, so the append finished. ``("discard", [])``: fewer of
    them followed by nothing or by a cut-off line, or one complete line that is not an
    entry, are what is left of an append that failed part way. ``("fail", [])``: anything
    else, which this commit did not write and recovery must not remove.
    """
    count = journal["count"]
    lines = tail.split(b"\n")
    rest = lines.pop()
    expected: list[AuditEntry] = []
    for offset, raw in enumerate(lines):
        entry = _parse_entry(raw)
        if entry is None or entry.seq != journal["after_seq"] + 1 + offset:
            break
        expected.append(entry)
    if len(expected) == len(lines) == count and not rest:
        if all(entry.event == BASELINE_EVENT for entry in expected[1:]):
            return "forward", expected
        return "fail", []
    torn = len(expected) == len(lines) < count
    garbled_last = (
        len(expected) == len(lines) - 1
        and len(lines) <= count
        and not rest
        and _parse_entry(lines[-1]) is None
    )
    return ("discard", []) if torn or garbled_last else ("fail", [])


def _journal_mismatch(journal: dict, log: bytes) -> str | None:
    """Why the journal cannot describe a commit to this log, or None when it can."""
    log_size, after_seq = journal["log_size"], journal["after_seq"]
    if log_size > len(log):
        return "log_size is beyond the end of the audit log"
    if log_size == 0:
        return None if after_seq == -1 else "after_seq must be -1 when log_size is 0"
    if log[log_size - 1 : log_size] != b"\n":
        return "log_size is not at the end of a line of the audit log"
    entry = _parse_entry(log[: log_size - 1].rsplit(b"\n", 1)[-1])
    if entry is None or entry.seq != after_seq:
        return "after_seq is not the seq of the entry that ends at log_size"
    return None


def _head_fits(journal: dict, log: bytes, outcome: str, appended: list[AuditEntry], head) -> bool:
    """Whether ``audit.head.json`` is one an interrupted commit of ``journal`` can leave.

    A commit writes the head only after every line of its append reached the log, so a
    discarded append leaves the head of the entry at ``after_seq``, and a kept one leaves
    that head or the head of its last entry. A project with no head file yet (last
    written by RiskForge 1.1) fits only while the log before the change holds no entry
    written by 2.0 or later. Anything else means the journal was not left by the commit
    that wrote this log, and recovery must not act on it.
    """
    before_entries, _errors = _parse_log(log[: journal["log_size"]])
    before = [entry for _label, entry in before_entries]
    if head is None:
        return not any(written_since_2_0(entry) for entry in before)
    allowed = []
    if before:
        allowed.append({"seq": before[-1].seq, "entry_hash": before[-1].entry_hash})
    if outcome == "forward":
        allowed.append({"seq": appended[-1].seq, "entry_hash": appended[-1].entry_hash})
    return head in allowed


_HEAD_DOES_NOT_FIT = (
    "txn.json describes an unfinished change that audit.head.json does not fit (the head "
    "file names neither the entry before that change nor its last entry), so it was not "
    "written by RiskForge for this log. Recovery refused it and changed nothing."
)


class _BadLine(ValueError):
    """A line of the audit log that is not exactly one stored entry."""


def _entry_from_line(raw: bytes) -> AuditEntry:
    """Parse one line of ``audit.jsonl``, which RiskForge writes as one UTF-8 JSON object.

    One ``\\r`` before the line feed is part of the line end (1.1.3 on Windows wrote
    ``\\r\\n``). Anything else on the line (a byte order mark, any other carriage
    return, white space, another encoding) is refused, so every reader of the log sees
    the same entries.
    """
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    if not raw:
        raise _BadLine("blank line")
    if raw.startswith(_BYTE_ORDER_MARKS):
        raise _BadLine("starts with a byte order mark")
    if b"\r" in raw:
        raise _BadLine("holds a carriage return")
    if raw != raw.strip():
        raise _BadLine("has white space around the entry")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _BadLine("not UTF-8 text") from exc
    try:
        refuse_deep_nesting(text)
    except StrictJsonError as exc:
        raise _BadLine(f"holds {exc}, which RiskForge never writes") from exc
    try:
        document = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise _BadLine(f"not valid JSON ({_first_line(exc)})") from exc
    try:
        return AuditEntry.model_validate(document)
    except ValidationError as exc:
        raise _BadLine(f"not a valid audit entry ({exc.error_count()} field error(s))") from exc


def _parse_entry(raw: bytes) -> AuditEntry | None:
    try:
        return _entry_from_line(raw)
    except _BadLine:
        return None


def _parse_log(data: bytes) -> tuple[list[tuple[str, AuditEntry]], list[str]]:
    """Every entry of the log with its line label, and every line that is not an entry.

    Lines end with ``\\n`` (or ``\\r\\n``); the log must end with one.
    """
    entries: list[tuple[str, AuditEntry]] = []
    errors: list[str] = []
    if not data:
        return entries, errors
    lines = data.split(b"\n")
    tail = lines.pop()
    for lineno, raw in enumerate(lines, start=1):
        try:
            entries.append((f"Line {lineno}", _entry_from_line(raw)))
        except _BadLine as exc:
            errors.append(f"Line {lineno}: {exc}.")
    if tail:
        errors.append(
            f"Line {len(lines) + 1}: the audit log does not end with a line break "
            "(an append was cut short or bytes were added)."
        )
    return entries, errors


class FileStore(StorageBackend):
    """Stores project state as YAML + JSONL under ``.riskforge/`` directory.

    This is the OSS default storage backend. State is git-committable,
    human-readable by regulators, and diff-resolvable by compliance teams.

    All blocking I/O is dispatched to a thread pool via
    :func:`asyncio.to_thread` so the implementation is safe inside an
    ``asyncio`` event loop without blocking the main thread.

    Parameters
    ----------
    project_dir:
        The project working directory.  All RiskForge data is stored
        under ``project_dir / ".riskforge"``.
    lock_timeout:
        Seconds ``unit_of_work()`` waits for another process to release the
        project lock before it raises :class:`ProjectLockedError`. Defaults to
        ``DEFAULT_LOCK_TIMEOUT`` (120 s).
    read_only:
        Read without locking, recovering or writing anything; every write raises
        ``PermissionError``. ``riskforge verify`` opens projects this way.
    """

    def __init__(
        self, project_dir: Path, lock_timeout: float | None = None, *, read_only: bool = False
    ) -> None:
        self._read_only = read_only
        # Read-only views of the state recovery would leave (see view_after_recovery):
        # where the log ends, staged files read in place of committed ones, the head.
        self._log_limit: int | None = None
        self._overlay: frozenset[str] = frozenset()
        self._head_override: dict | None = None
        self._root = project_dir / ".riskforge"
        self._key = os.path.realpath(self._root)
        self._lock_timeout = DEFAULT_LOCK_TIMEOUT if lock_timeout is None else lock_timeout
        self._audit_path = self._root / "audit.jsonl"
        self._head_path = self._root / "audit.head.json"
        self._journal_path = self._root / "txn.json"
        self._lock_path = self._root / "audit.lock"
        self._systems_dir = self._root / "systems"
        self._async_lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ #
    # Internal sync helpers (called via asyncio.to_thread)                #
    # ------------------------------------------------------------------ #

    def _require_writable(self) -> None:
        if self._read_only:
            raise PermissionError(f"{self._root} is opened read-only; nothing can be written.")

    def _ensure_dirs(self) -> None:
        """Create the ``.riskforge`` tree with chmod 700; write sentinel. Idempotent."""
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._systems_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, stat.S_IRWXU)
        os.chmod(self._systems_dir, stat.S_IRWXU)
        sentinel = self._root / SENTINEL
        if not sentinel.exists():
            sentinel.write_text(
                "Do not delete this directory. It contains the RiskForge audit log.\n",
                encoding="utf-8",
            )
            os.chmod(sentinel, stat.S_IRUSR | stat.S_IWUSR)

    def _gitignore_check(self) -> None:
        """Warn if ``riskforge.yaml`` in the project root would be git-tracked."""
        manifest = self._root.parent / "riskforge.yaml"
        try:
            result = subprocess.run(
                ["git", "check-ignore", "-q", str(manifest)],
                capture_output=True,
                cwd=self._root.parent,
            )
            # Exit 0 → ignored (good). Exit 1 → not ignored (warn).
            if result.returncode == 1:
                warnings.warn(
                    f"{manifest} is NOT listed in .gitignore. "
                    "Add '.riskforge/' to your .gitignore to avoid "
                    "committing sensitive risk assessment data.",
                    stacklevel=4,
                )
        except (FileNotFoundError, OSError):
            pass  # git not installed or not in a repo

    def _system_dir(self, system_id: str) -> Path:
        # Reject path traversal before system_id reaches the filesystem. Legitimate
        # ids are UUIDs (riskforge init); an id containing a path separator, "..",
        # or a null byte is an attempt to escape the systems/ directory. A benign
        # typo (no separators) still falls through to a clean "not found" error.
        if (
            system_id in ("", ".", "..")
            or "/" in system_id
            or "\\" in system_id
            or "\x00" in system_id
        ):
            raise InvalidSystemIdError(
                f"Invalid system id '{system_id}': must not contain path separators or '..'."
            )
        return self._systems_dir / system_id

    def _relative(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()

    def _scope(self) -> _Scope | None:
        return (_ACTIVE_UOW.get() or {}).get(self._key)

    def _note_written(self, kind: str, system_id: str) -> None:
        scope = self._scope()
        if scope is not None:
            scope.state.setdefault(WRITTEN_STATE_KEY, set()).add((kind, system_id))

    def unit_of_work_state(self) -> dict[str, Any] | None:
        """State of the open unit of work for this project, shared by every joined scope.

        Holds ``RECOVERED_STATE_KEY`` (True) when entering the scope finished or
        discarded a change an earlier unit of work left unfinished, and
        ``WRITTEN_STATE_KEY`` while writes are staged and not yet committed.
        """
        scope = self._scope()
        return None if scope is None else scope.state

    def _readable(self, path: Path) -> Path:
        """The file a read should see: this unit of work's staged copy, else the committed one."""
        scope = self._scope()
        rel = self._relative(path)
        if (scope is not None and rel in scope.staged) or rel in self._overlay:
            return _pending(path)
        return path

    def _write(self, path: Path, data: bytes) -> None:
        scope = self._scope()
        if scope is not None:
            _atomic_write(_pending(path), data)
            if self._relative(path) not in scope.staged:
                scope.staged.append(self._relative(path))
        else:
            _atomic_write(path, data)

    def _read_journal(self) -> dict | None:
        """The journal of an unfinished commit, or None when there is none.

        Raises
        ------
        StoredFileCorruptError
            If ``txn.json`` is not a journal RiskForge wrote: it does not parse, lacks a
            key, or names a file outside the system files a commit stages.
        """
        try:
            data = _read_stored(self._journal_path, "txn.json")
        except FileNotFoundError:
            return None

        def malformed(reason: str) -> StoredFileCorruptError:
            return StoredFileCorruptError(
                f"txn.json is not a journal RiskForge wrote ({reason}), so the unfinished "
                "change it describes cannot be finished or discarded."
            )

        try:
            journal = json.loads(data)
        except (ValueError, RecursionError) as exc:
            raise malformed("it does not parse as JSON") from exc
        if not isinstance(journal, dict):
            raise malformed("it is not a JSON object")
        journal.setdefault("count", 1)
        for key, lowest in (("after_seq", -1), ("log_size", 0), ("count", 1)):
            value = journal.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < lowest:
                raise malformed(f"{key} must be an integer of at least {lowest}")
        if journal["count"] > MAX_ENTRIES_PER_COMMIT:
            raise malformed(f"count is above {MAX_ENTRIES_PER_COMMIT}")
        files = journal.get("files")
        if not isinstance(files, list):
            raise malformed("files must be a list")
        for rel in files:
            parts = rel.split("/") if isinstance(rel, str) else []
            valid = len(parts) == 3 and parts[0] == "systems" and parts[2] in _JOURNAL_FILES
            if valid:
                try:
                    self._system_dir(parts[1])
                except InvalidSystemIdError:
                    valid = False
            if not valid:
                raise malformed(f"it names {rel!r}, which is not a system file")
        return journal

    def _log_bytes(self) -> bytes:
        """The audit log as stored, or up to where it ended before an unfinished change."""
        data = _read_stored(self._audit_path, "audit.jsonl", MAX_AUDIT_LOG_BYTES)
        return data if self._log_limit is None else data[: self._log_limit]

    def _checked_journal(self) -> tuple[dict, bytes] | None:
        """The journal and the whole audit log, once the journal is known to fit the log.

        Raises
        ------
        StoredFileCorruptError
            If the journal is malformed or cannot describe a commit to this log.
        """
        journal = self._read_journal()
        if journal is None:
            return None
        try:
            log = _read_stored(self._audit_path, "audit.jsonl", MAX_AUDIT_LOG_BYTES)
        except FileNotFoundError:
            log = b""
        problem = _journal_mismatch(journal, log)
        if problem is not None:
            raise StoredFileCorruptError(
                f"txn.json does not match the audit log ({problem}), so the unfinished "
                "change it describes cannot be finished or discarded."
            )
        return journal, log

    def _settle_log(self, journal: dict) -> AuditEntry | None:
        """The last entry an interrupted commit appended, or None after cutting off its append.

        The commit appended ``count`` lines with one write at ``log_size``;
        ``_settle_outcome`` decides whether they are kept, cut off, or left as they are
        with an error because this commit did not write them.
        """
        if not self._audit_path.exists():
            return None
        log_size = journal["log_size"]
        with self._audit_path.open("r+b") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell() <= log_size:
                return None
            fh.seek(log_size)
            outcome, appended = _settle_outcome(journal, fh.read())
            if outcome == "fail":
                raise AuditLogCorruptError(
                    "The audit log changed in a way an interrupted RiskForge commit cannot "
                    "explain, so it was left as it is."
                )
            if outcome == "forward":
                return appended[-1]
            fh.truncate(log_size)
            fh.flush()
            os.fsync(fh.fileno())
        return None

    def _write_head(self, seq: int, entry_hash: str) -> None:
        head = {"seq": seq, "entry_hash": entry_hash}
        _atomic_write(self._head_path, json.dumps(head).encode("utf-8"))

    def _recover(self) -> None:
        """Finish or discard a change that an earlier unit of work left behind.

        The journal names the staged files, the chain head before the append, the log
        length before it and how many lines the append wrote. If every appended entry is
        complete, the staged files are renamed into place; otherwise what reached the log
        is cut off and the staged files are deleted. A journal RiskForge did not write
        raises ``StoredFileCorruptError`` and nothing is touched, as does a journal that
        ``audit.head.json`` does not fit (see ``_head_fits``). Any other pending or temp
        file is an uncommitted write and is deleted, and a system directory left empty by
        that is removed. When a journal was acted on, the open scope's state records it
        under ``RECOVERED_STATE_KEY``.
        """
        emptied: set[Path] = set()
        checked = self._checked_journal()
        if checked is not None:
            journal, log = checked
            outcome, appended_entries = _settle_outcome(journal, log[journal["log_size"] :])
            if len(log) > journal["log_size"] and outcome == "fail":
                raise AuditLogCorruptError(
                    "The audit log changed in a way an interrupted RiskForge commit cannot "
                    "explain, so it was left as it is."
                )
            if len(log) <= journal["log_size"]:
                outcome, appended_entries = "discard", []
            if not _head_fits(journal, log, outcome, appended_entries, self._read_head()):
                raise StoredFileCorruptError(_HEAD_DOES_NOT_FIT)
            scope = self._scope()
            if scope is not None:
                scope.state[RECOVERED_STATE_KEY] = True
            appended = self._settle_log(journal)
            for rel in journal["files"]:
                final = self._root / rel
                pending = _pending(final)
                if appended is not None and pending.exists():
                    os.replace(pending, final)
                    _fsync_dir(final.parent)
                elif appended is None:
                    pending.unlink(missing_ok=True)
                    emptied.add(final.parent)
            if appended is not None:
                self._write_head(appended.seq, appended.entry_hash)
            self._journal_path.unlink()
            _fsync_dir(self._root)
        if self._systems_dir.exists():
            leftovers = [
                *self._systems_dir.glob(f"*/*{PENDING_SUFFIX}"),
                *self._systems_dir.glob("*/.*.tmp"),
            ]
            for leftover in leftovers:
                leftover.unlink()
                emptied.add(leftover.parent)
        if self._root.exists():
            for leftover in self._root.glob(".*.tmp"):
                leftover.unlink()
        for directory in emptied:
            if directory.parent == self._systems_dir and directory.is_dir():
                if not any(directory.iterdir()):
                    directory.rmdir()
        scope = self._scope()
        if scope is not None:
            scope.staged.clear()
            scope.state.pop(WRITTEN_STATE_KEY, None)

    # ------------------------------------------------------------------ #
    # Unit of work                                                         #
    # ------------------------------------------------------------------ #

    @contextlib.asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[None]:
        """Hold the project write lock; commit staged writes with the audit entry.

        Re-entrant: a nested call, from this or another FileStore for the same
        project, joins the open scope. On entry, and on exit, the scope finishes or
        discards anything an interrupted commit left behind.

        Raises
        ------
        ProjectLockedError
            If another process holds the project lock for longer than ``lock_timeout``.
        RuntimeError
            If the scope ends without an error but with writes that no audit entry
            recorded. The writes are discarded.
        """
        if self._read_only:
            if self._journal_path.exists():
                raise PendingChangeError(
                    f"{self._journal_path} records a change that is in progress or unfinished. "
                    "Any riskforge command that can write to the project finishes or discards it."
                )
            yield
            return
        active = _ACTIVE_UOW.get() or {}
        if self._key in active:
            yield
            return
        loop = asyncio.get_running_loop()
        if self._async_lock is None or self._lock_loop is not loop:
            # CLI commands call asyncio.run more than once on one store, and an
            # asyncio.Lock must not outlive the loop it was first used on.
            self._async_lock = asyncio.Lock()
            self._lock_loop = loop
        async with self._async_lock:
            await asyncio.to_thread(self._ensure_dirs)
            lock = FileLock(str(self._lock_path))
            deadline = loop.time() + self._lock_timeout
            while True:
                try:
                    lock.acquire(timeout=0)
                    break
                except Timeout:
                    if loop.time() >= deadline:
                        raise ProjectLockedError(
                            "Another riskforge process holds the project lock "
                            f"({self._lock_path}); gave up after {self._lock_timeout:g} s. "
                            "Try again when it has finished."
                        ) from None
                    await asyncio.sleep(_LOCK_POLL_SECONDS)
            scope = _Scope()
            token = _ACTIVE_UOW.set({**active, self._key: scope})
            try:
                await asyncio.to_thread(self._recover)
                try:
                    yield
                except BaseException as exc:
                    try:
                        await asyncio.to_thread(self._recover)
                    except Exception as recovery_error:
                        exc.add_note(
                            "Cleaning up the project after this error also failed: "
                            f"{recovery_error!r}. The next RiskForge command retries it."
                        )
                    raise
                unrecorded = list(scope.staged)
                await asyncio.to_thread(self._recover)
                if unrecorded:
                    raise RuntimeError(
                        "A unit of work ended with writes that no audit entry recorded, so "
                        f"they were discarded: {', '.join(unrecorded)}."
                    )
            finally:
                _ACTIVE_UOW.reset(token)
                lock.release()

    # ------------------------------------------------------------------ #
    # Project lifecycle                                                    #
    # ------------------------------------------------------------------ #

    async def init_project(self, project_id: str, metadata: dict) -> None:
        """Initialise the ``.riskforge`` directory for a new project.

        Writes ``riskforge.yaml`` at the project root with chmod 600.

        Raises
        ------
        ProjectExistsError
            If ``riskforge.yaml`` already exists (a ``FileExistsError``).
        ManifestMissingError
            If ``riskforge.yaml`` is gone but ``.riskforge/`` still holds a project.
            Either way nothing is written.
        """

        self._require_writable()
        manifest_path = self._root.parent / "riskforge.yaml"
        exists_message = (
            f"A RiskForge project already exists in {self._root.parent.resolve()} "
            "(riskforge.yaml found)."
        )

        def _sync() -> None:
            if manifest_path.exists():
                raise ProjectExistsError(exists_message)
            self._raise_if_manifest_missing()
            self._ensure_dirs()
            self._gitignore_check()
            content = {"project_id": project_id, "schema_version": "1.0.0", **metadata}
            data = yaml.dump(content, sort_keys=False, allow_unicode=True).encode("utf-8")
            try:
                fd = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600)
            except FileExistsError as exc:
                raise ProjectExistsError(exists_message) from exc
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            logger.info("Project '%s' initialised at %s", project_id, self._root.parent)

        await asyncio.to_thread(_sync)

    def _raise_if_manifest_missing(self) -> None:
        """Raise ManifestMissingError when ``.riskforge/`` holds an audit log or a system.

        Call only once ``riskforge.yaml`` is known to be absent.
        """

        # lstat, not exists(): a dangling symlink still counts, and a path that cannot be
        # checked (permission denied) counts as holding data so the command refuses cleanly.
        def present(path: Path) -> bool:
            try:
                path.lstat()
            except (FileNotFoundError, NotADirectoryError):
                return False
            except OSError:
                return True
            return True

        holds_data = any(
            present(path) for path in (self._audit_path, self._head_path, self._journal_path)
        )
        if not holds_data:
            try:
                holds_data = any(self._systems_dir.iterdir())
            except (FileNotFoundError, NotADirectoryError):
                holds_data = False
            except OSError:
                holds_data = True
        if holds_data:
            raise ManifestMissingError(
                f"riskforge.yaml is missing from {self._root.parent.resolve()}, "
                "but .riskforge/ there holds an existing RiskForge project."
            )

    def ensure_project(self) -> None:
        """Raise ProjectNotFoundError unless ``riskforge.yaml`` exists.

        Raises the ManifestMissingError subclass when ``.riskforge/`` still holds a project.
        """
        manifest = self._root.parent / "riskforge.yaml"
        if not manifest.exists():
            self._raise_if_manifest_missing()
            raise ProjectNotFoundError(
                f"No RiskForge project in {self._root.parent.resolve()} (riskforge.yaml not found)."
            )

    def protected_paths(self) -> tuple[Path, ...]:
        """``.riskforge/`` and the ``riskforge.yaml`` manifest."""
        return (self._root, self._root.parent / "riskforge.yaml")

    def read_project_id(self) -> str | None:
        """The manifest's ``project_id``, or None when the manifest cannot be read."""
        try:
            data = _read_stored(self._root.parent / "riskforge.yaml", "riskforge.yaml")
            manifest = _load_yaml(data, "riskforge.yaml")
        except (FileNotFoundError, StoredFileCorruptError):
            return None
        project_id = manifest.get("project_id") if isinstance(manifest, dict) else None
        return project_id if isinstance(project_id, str) else None

    # ------------------------------------------------------------------ #
    # AI system CRUD                                                       #
    # ------------------------------------------------------------------ #

    async def write_system(self, system_id: str, data: AISystem) -> None:
        """Persist *data* to ``systems/{system_id}/system.yaml`` with chmod 600."""
        self._require_writable()

        def _sync() -> None:
            self._ensure_dirs()
            sdir = self._system_dir(system_id)
            sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(sdir, stat.S_IRWXU)
            payload = yaml.dump(data.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
            self._write(sdir / "system.yaml", payload.encode("utf-8"))
            self._note_written("system", system_id)
            logger.debug("Wrote system '%s'", system_id)

        await asyncio.to_thread(_sync)

    async def read_system(self, system_id: str) -> AISystem:
        """Read ``systems/{system_id}/system.yaml`` and return an :class:`AISystem`.

        Raises
        ------
        SystemNotFoundError
            If the YAML file does not exist (a ``FileNotFoundError``).
        """

        return AISystem.model_validate(await self.read_system_document(system_id))

    async def read_system_document(self, system_id: str) -> dict:
        """Return ``system.yaml`` as stored, as a dict.

        Raises
        ------
        SystemNotFoundError
            If the YAML file does not exist (a ``FileNotFoundError``).
        StoredFileCorruptError
            If it does not parse as YAML.
        """

        def _sync() -> dict:
            path = self._readable(self._system_dir(system_id) / "system.yaml")
            try:
                data = _read_stored(path, "system.yaml")
            except FileNotFoundError:
                raise SystemNotFoundError(f"No system '{system_id}' in this project.") from None
            return _load_yaml(data, "system.yaml")  # type: ignore[return-value]

        return await asyncio.to_thread(_sync)

    async def list_systems(self) -> list[str]:
        """Return the sorted ids of systems whose ``system.yaml`` is committed."""

        def _sync() -> list[str]:
            return [name for name in self._system_directories() if self._has_record(name)]

        return await asyncio.to_thread(_sync)

    async def list_system_directories(self) -> list[str]:
        """Return the sorted names of every directory under ``systems/``, whatever it holds.

        Raises
        ------
        StoredFileCorruptError
            If ``systems/`` cannot be listed.
        """
        return await asyncio.to_thread(self._system_directories)

    def _has_record(self, name: str) -> bool:
        """Whether ``systems/<name>/system.yaml`` is there to read.

        A directory that cannot be searched counts as having one, so reading it reports
        the directory instead of the system silently disappearing.
        """
        if f"systems/{name}/system.yaml" in self._overlay:
            return True
        try:
            os.stat(self._systems_dir / name / "system.yaml")
        except (FileNotFoundError, NotADirectoryError):
            return False
        except OSError:
            return True
        return True

    def _system_directories(self) -> list[str]:
        if not self._systems_dir.exists():
            return []
        try:
            names = sorted(entry.name for entry in self._systems_dir.iterdir() if entry.is_dir())
        except OSError as exc:
            raise StoredFileCorruptError(
                f"systems/ cannot be listed: {exc.strerror or exc}."
            ) from exc
        if self._log_limit is None and not self._overlay and self._head_override is None:
            return names
        return [name for name in names if self._survives_recovery(name)]

    def _survives_recovery(self, name: str) -> bool:
        """Whether recovery would keep this directory (it removes ones it empties)."""
        if any(rel.startswith(f"systems/{name}/") for rel in self._overlay):
            return True
        try:
            children = [child.name for child in (self._systems_dir / name).iterdir()]
        except OSError:
            return True
        return any(
            not child.endswith(PENDING_SUFFIX)
            and not (child.startswith(".") and child.endswith(".tmp"))
            for child in children
        )

    # ------------------------------------------------------------------ #
    # Risk register CRUD                                                   #
    # ------------------------------------------------------------------ #

    async def write_register(self, system_id: str, register: RiskRegister) -> None:
        """Persist a :class:`RiskRegister` as two files.

        Writes:
        - ``systems/{system_id}/register.yaml``: register metadata + risk items
        - ``systems/{system_id}/mitigations.yaml``: flat mitigation catalogue
          with back-links to each parent risk item
        """
        self._require_writable()

        def _sync() -> None:
            self._ensure_dirs()
            sdir = self._system_dir(system_id)
            sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(sdir, stat.S_IRWXU)
            reg_dict = register.model_dump(mode="json")
            catalogue = [
                {**mitigation, "_risk_item_id": item["id"]}
                for item in reg_dict.get("items", [])
                for mitigation in item.get("mitigations", [])
            ]
            reg_bytes = yaml.dump(reg_dict, sort_keys=False, allow_unicode=True).encode("utf-8")
            mit_bytes = yaml.dump(
                {"mitigations": catalogue}, sort_keys=False, allow_unicode=True
            ).encode("utf-8")
            self._write(sdir / "register.yaml", reg_bytes)
            self._note_written("register", system_id)
            self._write(sdir / "mitigations.yaml", mit_bytes)
            logger.debug(
                "Wrote register for system '%s' (%d items, %d mitigations)",
                system_id,
                len(reg_dict.get("items", [])),
                len(catalogue),
            )

        await asyncio.to_thread(_sync)

    async def read_register_document(self, system_id: str) -> dict:
        """Return ``register.yaml`` as stored: ``yaml.safe_load`` of its bytes (ADR-03).

        Inside a unit of work this is the staged copy, so the audit entry that commits a
        register write fingerprints the exact text that was written.

        Raises
        ------
        RegisterNotFoundError
            If ``register.yaml`` does not exist for *system_id* (a ``FileNotFoundError``).
        StoredFileCorruptError
            If it does not parse as YAML.
        """

        def _sync() -> dict:
            path = self._readable(self._system_dir(system_id) / "register.yaml")
            try:
                data = _read_stored(path, "register.yaml")
            except FileNotFoundError:
                raise RegisterNotFoundError(
                    f"System '{system_id}' has no risk register yet."
                ) from None
            return _load_yaml(data, "register.yaml")  # type: ignore[return-value]

        return await asyncio.to_thread(_sync)

    async def read_register(self, system_id: str) -> RiskRegister:
        """Read and reconstruct a :class:`RiskRegister` from YAML.

        Raises
        ------
        RegisterNotFoundError
            If ``register.yaml`` does not exist for *system_id* (a ``FileNotFoundError``).
        """
        return RiskRegister.model_validate(await self.read_register_document(system_id))

    # ------------------------------------------------------------------ #
    # Audit log                                                            #
    # ------------------------------------------------------------------ #

    async def append_audit(self, entries: AuditEntry | Sequence[AuditEntry]) -> None:
        """Append one entry, or several chained entries, and commit the writes staged before.

        Order: journal (the log length before the append and the number of lines), one
        fsynced write of every line, rename of each staged file, head file for the last
        entry, journal removed. A crash at any point leaves a state ``_recover`` can
        finish (every line reached the log) or discard (not all did, and what did is cut
        off), so a change and all its entries commit together.

        Raises
        ------
        RuntimeError
            If called outside ``unit_of_work()``.
        ValueError
            If the entries do not follow one another (seq and prev_hash).
        """
        self._require_writable()
        batch = [entries] if isinstance(entries, AuditEntry) else list(entries)
        if not batch:
            raise ValueError("append_audit needs at least one entry.")
        for before, after in zip(batch, batch[1:], strict=False):
            if after.seq != before.seq + 1 or after.prev_hash != before.entry_hash:
                raise ValueError("Entries appended together must be chained in order.")
        scope = self._scope()
        if scope is None:
            raise RuntimeError("append_audit must run inside FileStore.unit_of_work().")

        def _sync() -> None:
            created = not self._audit_path.exists()
            journal = {
                "after_seq": batch[0].seq - 1,
                "log_size": 0 if created else self._audit_path.stat().st_size,
                "count": len(batch),
                "files": list(scope.staged),
            }
            _atomic_write(self._journal_path, json.dumps(journal).encode("utf-8"))
            data = b"".join(
                (json.dumps(entry_to_dict(entry), separators=(",", ":")) + "\n").encode("utf-8")
                for entry in batch
            )
            fd = os.open(
                self._audit_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _O_BINARY, 0o600
            )
            try:
                written = os.write(fd, data)
                if written != len(data):
                    raise OSError(
                        errno.EIO, f"Wrote {written} of {len(data)} bytes to the audit log."
                    )
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(self._audit_path, stat.S_IRUSR | stat.S_IWUSR)
            if created:
                _fsync_dir(self._root)
            staged = [self._root / rel for rel in scope.staged]
            for path in staged:
                os.replace(_pending(path), path)
            for directory in {path.parent for path in staged}:
                _fsync_dir(directory)
            scope.staged.clear()
            scope.state.pop(WRITTEN_STATE_KEY, None)
            self._write_head(batch[-1].seq, batch[-1].entry_hash)
            self._journal_path.unlink()

        await asyncio.to_thread(_sync)

    async def read_audit(
        self,
        system_id: str | None = None,
        since_seq: int = 0,
    ) -> AsyncIterator[AuditEntry]:
        """Async generator streaming :class:`AuditEntry` records.

        Parameters
        ----------
        system_id:
            Filter by system ID string.  Pass ``None`` to yield all entries.
        since_seq:
            Yield only entries with ``seq >= since_seq``.

        Yields
        ------
        AuditEntry

        Raises
        ------
        AuditLogCorruptError
            If a line is not a valid audit entry. A corrupt line is never skipped.
        """

        def _read() -> list[tuple[str, AuditEntry]]:
            try:
                data = self._log_bytes()
            except FileNotFoundError:
                return []
            except StoredFileCorruptError as exc:
                raise AuditLogCorruptError(str(exc)) from exc
            entries, errors = _parse_log(data)
            if errors:
                raise AuditLogCorruptError(f"The audit log is not valid. {errors[0]}")
            return entries

        for _label, entry in await asyncio.to_thread(_read):
            if entry.seq < since_seq:
                continue
            if system_id is not None and entry.system_id != system_id:
                continue
            yield entry

    async def read_last_audit_entry(self) -> AuditEntry | None:
        """Return the last audit entry, parsing only the final line."""

        def _sync() -> AuditEntry | None:
            try:
                data = self._log_bytes()
            except FileNotFoundError:
                return None
            except StoredFileCorruptError as exc:
                raise AuditLogCorruptError(str(exc)) from exc
            if not data:
                return None
            if not data.endswith(b"\n"):
                raise AuditLogCorruptError(
                    "The audit log does not end with a line break, so its last entry is not "
                    "complete."
                )
            last = data[:-1].rsplit(b"\n", 1)[-1]
            try:
                return _entry_from_line(last)
            except _BadLine as exc:
                raise AuditLogCorruptError(f"The last audit log line is {exc}.") from exc

        return await asyncio.to_thread(_sync)

    async def read_audit_head(self) -> dict | None:
        """Return ``audit.head.json`` as ``{"seq": int, "entry_hash": str}``, or None if absent.

        Raises
        ------
        StoredFileCorruptError
            If the head file does not parse, lacks ``seq`` or ``entry_hash``, or cannot
            be read.
        """

        if self._head_override is not None:
            return dict(self._head_override)
        return await asyncio.to_thread(self._read_head)

    def _read_head(self) -> dict | None:
        try:
            data = _read_stored(self._head_path, "audit.head.json")
        except FileNotFoundError:
            return None
        try:
            head = json.loads(data)
        except (ValueError, RecursionError) as exc:
            raise StoredFileCorruptError(
                f"audit.head.json does not parse: {_first_line(exc)}."
            ) from exc
        if (
            not isinstance(head, dict)
            or not isinstance(head.get("seq"), int)
            or isinstance(head.get("seq"), bool)
            or not isinstance(head.get("entry_hash"), str)
        ):
            raise StoredFileCorruptError(
                "audit.head.json does not parse: it needs an integer seq and a string entry_hash."
            )
        return {"seq": head["seq"], "entry_hash": head["entry_hash"]}

    async def read_commit_markers(self) -> tuple[bytes | None, bytes | None]:
        """Return the raw bytes of ``txn.json`` and ``audit.head.json``, each None if absent.

        A marker that cannot be read is returned as a fixed description of why, so two
        reads still compare equal while nothing changes.
        """

        def _read(path: Path) -> bytes | None:
            try:
                return _read_stored(path, path.name)
            except FileNotFoundError:
                return None
            except StoredFileCorruptError as exc:
                return f"unreadable: {exc}".encode()

        def _sync() -> tuple[bytes | None, bytes | None]:
            return _read(self._journal_path), _read(self._head_path)

        return await asyncio.to_thread(_sync)

    async def read_pending_change(self) -> PendingChange | None:
        """The change ``txn.json`` records as unfinished, or None when there is none.

        Raises
        ------
        StoredFileCorruptError
            If ``txn.json`` is not a journal RiskForge wrote or cannot be read.
        """
        journal = await asyncio.to_thread(self._read_journal)
        if journal is None:
            return None
        return PendingChange(systems=frozenset(rel.split("/")[1] for rel in journal["files"]))

    async def view_after_recovery(self) -> FileStore:
        """A read-only view of the project as recovery of the unfinished change would leave it.

        Nothing is written. If recovery would cut off the append, the view ends the log at
        ``log_size`` and reads the committed files and head. If it would keep the append,
        the view reads the staged files in place of the committed ones and takes the last
        appended entry as the head, after checking that the stored head is the one before
        the change or the one after it.

        Raises
        ------
        StoredFileCorruptError
            If the journal is malformed, does not fit the log, or recovery would refuse it.
        """
        return await asyncio.to_thread(self._view_after_recovery)

    def _view_after_recovery(self) -> FileStore:
        checked = self._checked_journal()
        if checked is None:
            return self
        journal, log = checked
        log_size = journal["log_size"]
        outcome, appended = _settle_outcome(journal, log[log_size:])
        if outcome == "fail":
            raise StoredFileCorruptError(
                "txn.json records a change that does not match the end of the audit log, so "
                "recovery would refuse it."
            )
        if len(log) <= log_size:
            outcome, appended = "discard", []
        if not _head_fits(journal, log, outcome, appended, self._read_head()):
            raise StoredFileCorruptError(_HEAD_DOES_NOT_FIT)
        view = FileStore(self._root.parent, self._lock_timeout, read_only=True)
        if outcome == "discard":
            view._log_limit = log_size
            return view
        after = {"seq": appended[-1].seq, "entry_hash": appended[-1].entry_hash}
        view._overlay = frozenset(
            rel for rel in journal["files"] if _pending(self._root / rel).exists()
        )
        view._head_override = after
        return view

    async def verify_chain(self) -> tuple[bool, list[str]]:
        """Check that every line is one entry, links to the one before and hashes to its value.

        Lines are read byte for byte (see ``_entry_from_line``), the same way every other
        reader of the log reads them. This covers the chain only;
        ``riskforge.engine.integrity.check_integrity`` adds the head file, register
        fingerprints and the files on disk (ADR-03 section 5).

        Returns
        -------
        tuple[bool, list[str]]
            ``(True, [])`` if the chain is intact, or
            ``(False, [<error>, ...])`` listing every failure found.
        """

        def _sync() -> tuple[bool, list[str]]:
            try:
                data = self._log_bytes()
            except FileNotFoundError:
                data = b""
            except StoredFileCorruptError as exc:
                return False, [str(exc)]
            labelled, errors = _parse_log(data)
            errors.extend(verify_links(labelled))
            return not errors, errors

        return await asyncio.to_thread(_sync)
