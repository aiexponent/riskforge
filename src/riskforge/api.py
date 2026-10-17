"""The supported Python API of RiskForge.

Names listed in ``__all__`` follow semantic versioning from 2.0.0: a release that removes
one or changes its behaviour incompatibly is a new major version. Everything else in the
package is internal. See docs/library-api.md.

This module must not import ``riskforge.cli`` or WeasyPrint, so an application that
embeds the engine does not load the command line or the PDF stack.
"""

from __future__ import annotations

from riskforge.engine.assess import AssessEngine, keyword_matches
from riskforge.engine.audit import AuditEngine
from riskforge.engine.diff import FieldChange, ItemChange, RegisterDiff, diff_registers
from riskforge.engine.export import (
    ExportEngine,
    ExportError,
    ExportResult,
    SchemaViolationError,
    ValidationGateError,
    build_cross_references,
)
from riskforge.engine.integrity import (
    ChangeInProgressError,
    IntegrityError,
    IntegrityReport,
    check_integrity,
    check_integrity_settled,
    reads_checked_against,
    require_intact,
)
from riskforge.engine.risk import (
    AmbiguousRiskIdError,
    RiskEngine,
    RiskNotFoundError,
    UpsertOutcome,
    UpsertResult,
    origin_key,
)
from riskforge.engine.system import SystemEngine
from riskforge.engine.tests import TestDerivationEngine
from riskforge.engine.validate import GateResult, GateStatus, ValidateEngine
from riskforge.integrity.canonical import canonical_json, document_fingerprint
from riskforge.integrity.receipts import (
    InvalidReceiptError,
    ReceiptFileError,
    build_receipt,
    check_receipt,
    read_receipt_file,
    receipt_from_document,
)
from riskforge.integrity.rmf import (
    RmfCheck,
    RmfFileError,
    UnsupportedRmfVersionError,
    check_rmf_document,
    content_digest,
    read_rmf_file,
    rmf_signing_message,
    signoff_signing_message,
)
from riskforge.integrity.signing import (
    Ed25519Signer,
    KeyFileError,
    generate_key_pair_pem,
    key_id_for,
    load_public_key_b64,
    verify_signature,
    write_key_pair,
)
from riskforge.integrity.strict_json import NumberTooLongError, StrictJsonError
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.receipt import Receipt
from riskforge.models.register import RiskRegister
from riskforge.models.requirements import TestRequirement
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.models.rmf import (
    ChainProof,
    CrossReference,
    PublicKeyRecord,
    RiskManagementFile,
    RmfSignature,
    SignOff,
    rmf_document,
)
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.plugins.registry import PluginRegistry
from riskforge.storage.base import StorageBackend
from riskforge.storage.errors import (
    AuditLogCorruptError,
    PendingChangeError,
    ProjectExistsError,
    ProjectNotFoundError,
    RegisterNotFoundError,
    SystemNotFoundError,
)
from riskforge.storage.filesystem import FileStore

__all__ = [
    "AISystem",
    "AmbiguousRiskIdError",
    "AnnexIIICategory",
    "AssessEngine",
    "AuditActor",
    "AuditEngine",
    "AuditEntry",
    "AuditLogCorruptError",
    "ChainProof",
    "ChangeInProgressError",
    "CrossReference",
    "Ed25519Signer",
    "ExportEngine",
    "ExportError",
    "ExportResult",
    "FieldChange",
    "FileStore",
    "GateResult",
    "GateStatus",
    "IntegrityError",
    "IntegrityReport",
    "InvalidReceiptError",
    "ItemChange",
    "KeyFileError",
    "Likelihood",
    "Mitigation",
    "NumberTooLongError",
    "PendingChangeError",
    "PluginRegistry",
    "ProjectExistsError",
    "ProjectNotFoundError",
    "PublicKeyRecord",
    "Receipt",
    "ReceiptFileError",
    "RegisterDiff",
    "RegisterNotFoundError",
    "RiskDimension",
    "RiskEngine",
    "RiskItem",
    "RiskManagementFile",
    "RiskNotFoundError",
    "RiskRegister",
    "RmfCheck",
    "RmfFileError",
    "RmfSignature",
    "SchemaViolationError",
    "Severity",
    "SignOff",
    "StorageBackend",
    "StrictJsonError",
    "SystemEngine",
    "SystemNotFoundError",
    "TestDerivationEngine",
    "TestRequirement",
    "UnsupportedRmfVersionError",
    "UpsertOutcome",
    "UpsertResult",
    "ValidateEngine",
    "ValidationGateError",
    "build_cross_references",
    "build_receipt",
    "canonical_json",
    "check_integrity",
    "check_integrity_settled",
    "check_receipt",
    "check_rmf_document",
    "content_digest",
    "diff_registers",
    "document_fingerprint",
    "generate_key_pair_pem",
    "key_id_for",
    "keyword_matches",
    "load_public_key_b64",
    "origin_key",
    "read_receipt_file",
    "read_rmf_file",
    "reads_checked_against",
    "receipt_from_document",
    "require_intact",
    "rmf_document",
    "rmf_signing_message",
    "signoff_signing_message",
    "verify_signature",
    "write_key_pair",
]
