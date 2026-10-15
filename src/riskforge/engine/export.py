"""ExportEngine: build the RMF, render it, write it atomically, then record the export (ADR-04)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import jsonschema

from riskforge.engine.audit import AuditEngine, StagedEntries
from riskforge.engine.integrity import latest_fingerprints
from riskforge.engine.validate import GateResult, GateStatus, ValidateEngine
from riskforge.integrity.canonical import UnfingerprintableDocumentError, document_fingerprint
from riskforge.integrity.chain import entry_signing_message
from riskforge.integrity.receipts import build_receipt
from riskforge.integrity.rmf import content_digest, load_schema, rmf_signing_message
from riskforge.integrity.signing import key_id_for, verify_signature
from riskforge.models.audit import AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.risk import RiskItem
from riskforge.models.rmf import (
    RMF_SCHEMA_VERSION,
    ChainProof,
    CrossReference,
    PublicKeyRecord,
    RiskManagementFile,
    RmfSignature,
    rmf_document,
)
from riskforge.plugins.registry import PluginRegistry
from riskforge.storage.base import StorageBackend

if TYPE_CHECKING:
    from riskforge.integrity.signing import Ed25519Signer

CHECKPOINT_EVENT = "register.checkpoint"

# Every temporary file an export writes starts with this, so the next export to the
# directory can find and remove one an interrupted export left behind.
TEMP_PREFIX = ".riskforge-export-"
TEMP_SUFFIX = ".tmp"

_IS_WINDOWS = os.name == "nt"


class ExportError(RuntimeError):
    """An export that was refused or failed before its file was written. Nothing was recorded."""


class SchemaViolationError(ExportError):
    """The RMF document failed schema validation at export time."""


class ValidationGateError(ExportError):
    """FAIL gates block an export that was not forced."""

    def __init__(self, results: list[GateResult]) -> None:
        failing = [r.gate_id for r in results if r.status == GateStatus.FAIL]
        super().__init__("Validation gates failed: " + ", ".join(failing))
        self.results = results


class ExportTargetError(ExportError):
    """The output path cannot be written: a missing or unwritable directory, or a full disk."""


class CheckpointError(ExportError):
    """The register does not read back as the current model serialises it, so no checkpoint."""


class MissingPublicKeyError(ExportError):
    """A chain proof entry is signed by a key the export was not given."""


class EntrySignatureError(ExportError):
    """A signed chain proof entry does not verify with its key."""


@dataclass(frozen=True)
class ExportResult:
    """What one export wrote and recorded."""

    path: Path
    export_id: str
    content_digest: str
    file_sha256: str
    entry: AuditEntry
    checkpoint: AuditEntry | None


def build_cross_references(items: list[RiskItem]) -> list[CrossReference]:
    """One cluster per article reference, with the first NIST and ISO reference seen for it."""
    clusters: OrderedDict[str, dict] = OrderedDict()
    for item in items:
        for art in item.article_refs:
            cluster = clusters.setdefault(art, {"ids": [], "nist": "", "iso": ""})
            cluster["ids"].append(item.id)
            if not cluster["nist"]:
                cluster["nist"] = (
                    item.nist_rmf_refs[0] if item.nist_rmf_refs else ""
                ) or item.nist_rmf_ref
            if not cluster["iso"]:
                cluster["iso"] = (
                    item.iso42001_refs[0] if item.iso42001_refs else ""
                ) or item.iso42001_ref
    return [
        CrossReference(
            article_ref=art,
            risk_item_ids=cluster["ids"],
            nist_rmf_ref=cluster["nist"],
            iso42001_ref=cluster["iso"],
        )
        for art, cluster in clusters.items()
    ]


def _fsync_dir(directory: Path) -> None:
    if _IS_WINDOWS:
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _reason(exc: OSError) -> str:
    return exc.strerror or str(exc)


def _refuse_protected_target(target: Path, protected: Sequence[Path]) -> None:
    """Refuse an output path that is a directory or part of the project's own files.

    The target and each of its parents are compared, after following symlinks, with
    every protected path, both by resolved path and by file identity (device and
    inode), so another spelling of the same directory is caught too.

    Raises
    ------
    ExportTargetError
        If ``target`` is an existing directory, or is or lies inside a protected path.
    """
    resolved = Path(os.path.realpath(target))
    if resolved.is_dir():
        raise ExportTargetError(f"{target} is a directory; pass a file path with --output.")
    by_path = {Path(os.path.realpath(path)): path for path in protected}
    by_identity: dict[tuple[int, int], Path] = {}
    for path in protected:
        try:
            info = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            continue
        by_identity[(info.st_dev, info.st_ino)] = path
    for candidate in (resolved, *resolved.parents):
        hit = by_path.get(candidate)
        if hit is None:
            try:
                info = os.stat(candidate)
            except (FileNotFoundError, NotADirectoryError):
                continue
            hit = by_identity.get((info.st_dev, info.st_ino))
        if hit is not None:
            raise ExportTargetError(
                f"{target} is part of the project's own files ({hit}); write the export "
                "somewhere else. Nothing was written."
            )


def _remove_stale_temporaries(directory: Path, older_than: float) -> None:
    """Remove export temporary files in ``directory`` last written before ``older_than``."""
    with os.scandir(directory) as entries:
        for entry in entries:
            if not (entry.name.startswith(TEMP_PREFIX) and entry.name.endswith(TEMP_SUFFIX)):
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                if entry.stat(follow_symlinks=False).st_mtime >= older_than:
                    continue
                os.unlink(entry.path)
            except FileNotFoundError:
                continue  # removed meanwhile


def _write_temporary(target: Path, data: bytes, older_than: float) -> Path:
    """Write ``data`` to a new temporary file next to ``target``, flushed to disk.

    The file is created exclusively under a unique name with mode 600 (``mkstemp``).

    Raises
    ------
    ExportTargetError
        If the directory is missing or the file cannot be written. Nothing is left.
    """
    directory = target.parent
    if not directory.is_dir():
        raise ExportTargetError(f"Output directory does not exist: {directory}")
    if target.is_dir():
        raise ExportTargetError(f"{target} is a directory; pass a file path with --output.")
    try:
        _remove_stale_temporaries(directory, older_than)
        fd, name = tempfile.mkstemp(dir=directory, prefix=TEMP_PREFIX, suffix=TEMP_SUFFIX)
    except OSError as exc:
        raise ExportTargetError(f"Cannot write to {directory}: {_reason(exc)}") from exc
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise ExportTargetError(f"Cannot write {target}: {_reason(exc)}") from exc
        raise
    return temporary


class ExportEngine:
    """Exports a system's register as an RMF document in a registered format."""

    DISCLOSURE_TEMPLATE = (
        "This document was produced using RiskForge v{version}, "
        "question bank version {qb_version}. "
        "It represents the team's documented risk assessment and has not been "
        "reviewed by a qualified legal professional. "
        "It does not constitute legal advice under the EU AI Act or any other regulation."
    )

    def __init__(
        self, registry: PluginRegistry, audit: AuditEngine, storage: StorageBackend
    ) -> None:
        self._registry = registry
        self._audit = audit
        self._storage = storage

    def build_rmf(
        self, register: RiskRegister, export_id: UUID | None = None
    ) -> RiskManagementFile:
        """The RMF content for ``register``, with its content digest and no provenance."""
        rmf = RiskManagementFile(
            id=export_id or uuid4(),
            rmf_schema_version=RMF_SCHEMA_VERSION,
            register=register,
            test_requirements=list(register.test_requirements),
            cross_references=build_cross_references(register.items),
            disclosure=self.DISCLOSURE_TEMPLATE.format(
                version=pkg_version("riskforge"), qb_version=register.question_bank_version
            ),
        )
        rmf.sha256_hash = content_digest(rmf_document(rmf))
        return rmf

    async def export(
        self,
        system_id: str,
        fmt: str,
        output_path: Path,
        *,
        force: bool = False,
        signer: Ed25519Signer | None = None,
        public_keys: Sequence[str] = (),
        export_id: UUID | None = None,
    ) -> ExportResult:
        """Export the system's register to ``output_path`` in the order ADR-04 section 7 fixes.

        Integrity check, gates (unless ``force``), a staged ``register.checkpoint`` when
        the stored register is not the current model's serialisation, the document with
        its chain proof, receipt and (with ``signer``) signature, schema validation, the
        rendered file written to a temporary file, the checkpoint committed, the rename,
        and last ``rmf.exported``. A failure before the commit leaves no file and records
        nothing. ``public_keys`` (base64 raw keys) name the keys of signed chain entries.

        Raises
        ------
        IntegrityError
            If the project fails its integrity check.
        ValidationGateError
            If a gate fails and ``force`` is not set.
        CheckpointError, SchemaViolationError, MissingPublicKeyError, EntrySignatureError,
        ExportTargetError
            As their docstrings say. Nothing is written or recorded.
        """
        exporter = self._registry.get_exporter(fmt)
        _refuse_protected_target(output_path, self._storage.protected_paths())
        async with self._audit.unit_of_work():
            locked_at = time.time()
            register = await self._audit.read_register(system_id)
            if not force:
                validator = ValidateEngine()
                results = validator.run(register)
                if validator.has_failures(results):
                    raise ValidationGateError(results)
            committed = [entry async for entry in self._storage.read_audit()]
            staged: StagedEntries | None = None
            if self._needs_checkpoint(system_id, register, committed):
                await self._storage.write_register(system_id, register)
                staged = await self._stage_checkpoint(system_id, register)
            proof = committed + list(staged.entries if staged else ())

            rmf = self.build_rmf(register, export_id)
            rmf.chain_proof = ChainProof(scope="project", entries=proof)
            fingerprint = latest_fingerprints(proof).get(system_id)
            rmf.receipt = build_receipt(proof[-1], system_id, fingerprint, signer)
            if signer is not None:
                rmf.signatures = [
                    RmfSignature(
                        key_id=signer.key_id,
                        signed_at=datetime.now(UTC),
                        signature=signer.sign(rmf_signing_message(rmf.sha256_hash)),
                    )
                ]
            rmf.public_keys = self._public_key_records(proof, signer, public_keys)
            self._validate(rmf)

            data = exporter.render(rmf)
            temporary = _write_temporary(output_path, data, locked_at)
            try:
                checkpoint = await self._audit.commit(staged) if staged else None
                os.replace(temporary, output_path)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            _fsync_dir(output_path.parent)

            file_sha256 = hashlib.sha256(data).hexdigest()
            entry = await self._audit.record(
                "rmf.exported",
                system_id,
                {
                    "export_id": str(rmf.id),
                    "format": fmt,
                    "sha256": rmf.sha256_hash,
                    "file_sha256": file_sha256,
                },
            )
        return ExportResult(
            path=output_path,
            export_id=str(rmf.id),
            content_digest=rmf.sha256_hash,
            file_sha256=file_sha256,
            entry=entry,
            checkpoint=checkpoint,
        )

    @staticmethod
    def _needs_checkpoint(
        system_id: str, register: RiskRegister, committed: list[AuditEntry]
    ) -> bool:
        """True when the chain's latest fingerprint is not the register's serialisation.

        That is when the chain records no fingerprint for the system, or one taken from
        a register last written by 1.1.3 or by an older model.
        """
        expected = document_fingerprint(register.model_dump(mode="json"))
        return latest_fingerprints(committed).get(system_id) != expected

    async def _stage_checkpoint(self, system_id: str, register: RiskRegister) -> StagedEntries:
        """The ``register.checkpoint`` entries for the register the export just staged.

        The staged register must read back as the model serialises it, so the checkpoint
        records a rewrite that changes no value.
        """
        self._audit.wrote_register(system_id)
        stored = await self._storage.read_register_document(system_id)
        try:
            matches = document_fingerprint(stored) == document_fingerprint(
                register.model_dump(mode="json")
            )
        except UnfingerprintableDocumentError:
            matches = False
        if not matches:
            raise CheckpointError(
                f"The register of system {system_id} does not read back as RiskForge writes "
                "it, so the export cannot record its exact state. Nothing was written. Run "
                "`riskforge verify` for details."
            )
        return await self._audit.stage(
            CHECKPOINT_EVENT, system_id, {"riskforge_version": pkg_version("riskforge")}
        )

    def _public_key_records(
        self,
        proof: list[AuditEntry],
        signer: Ed25519Signer | None,
        public_keys: Sequence[str],
    ) -> list[PublicKeyRecord]:
        """A record for every key that signed the file, its receipt or a chain proof entry."""
        known = {key_id_for(key): key for key in public_keys}
        for key_signer in (self._audit.signer, signer):
            if key_signer is not None:
                known[key_signer.key_id] = key_signer.public_key_b64
        used = {signer.key_id} if signer is not None else set()
        for entry in proof:
            if entry.key_id is None:
                continue
            key = known.get(entry.key_id)
            if key is None:
                raise MissingPublicKeyError(
                    f"Audit entry seq {entry.seq} is signed by {entry.key_id}, and the export "
                    "was not given that public key, so its chain proof could not be checked."
                )
            if not verify_signature(
                key, entry_signing_message(entry.entry_hash), entry.signature or ""
            ):
                raise EntrySignatureError(
                    f"The signature of audit entry seq {entry.seq} does not verify with "
                    f"{entry.key_id}. Run `riskforge verify --trusted-key PUBFILE`."
                )
            used.add(entry.key_id)
        return [PublicKeyRecord(key_id=key_id, public_key=known[key_id]) for key_id in sorted(used)]

    @staticmethod
    def _validate(rmf: RiskManagementFile) -> None:
        try:
            jsonschema.validate(rmf_document(rmf), load_schema(RMF_SCHEMA_VERSION))
        except jsonschema.ValidationError as exc:
            location = "/".join(str(part) for part in exc.absolute_path) or "the document"
            raise SchemaViolationError(
                f"The export does not fit RMF schema {RMF_SCHEMA_VERSION} at {location}: "
                f"{exc.message[:300]}. Nothing was written."
            ) from exc
