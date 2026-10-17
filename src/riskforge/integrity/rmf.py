"""RMF document rules: schema lookup, content digest, signing messages and strict reading (ADR-04)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from riskforge.integrity.canonical import canonical_json, document_fingerprint, sha256_hex
from riskforge.integrity.chain import entry_signing_message, verify_links
from riskforge.integrity.receipts import check_receipt
from riskforge.integrity.signing import decode_public_key, key_id_for, verify_signature
from riskforge.integrity.strict_json import loads_strict
from riskforge.models.audit import AuditEntry
from riskforge.models.receipt import Receipt

if TYPE_CHECKING:
    from riskforge.models.rmf import SignOff

SCHEMA_FILES = {"1.0.0": "rmf-1.0.0.schema.json", "1.1.0": "rmf-1.1.0.schema.json"}

RMF_SIGNING_DOMAIN = b"riskforge.rmf.v1\n"
SIGNOFF_SIGNING_DOMAIN = b"riskforge.signoff.v1\n"

# Under 1.0.0 these are blanked, not removed, exactly as 1.1.3 hashed them.
_BLANKED_1_0_0 = ("sha256_hash", "audit_entry_hash", "signed_by")

# The provenance blocks either verify themselves or describe the act of exporting, and
# change with every export of one register state, so the 1.1.0 digest leaves them out.
_NOT_DIGESTED_1_1_0 = (
    "id",
    "generated_at",
    "sha256_hash",
    "signatures",
    "public_keys",
    "chain_proof",
    "receipt",
)

RMF_1_0_0_CANNOT_BE_TRUSTED = (
    "RMF schema 1.0.0 cannot carry a signature, a chain proof or a receipt, so this file "
    "cannot pass a check that requires a trusted key or a receipt."
)

# The last note of a pass without a trusted key: every block can be rebuilt (ADR-04
# section 6, what each record catches).
SELF_CONSISTENT_ONLY = (
    "No trusted key was given, so this shows only that the file is consistent with "
    "itself: anyone can rebuild its chain proof, receipt and signatures. To check who "
    "made it, pass --trusted-key with the signer's public key"
)
_AND_A_RECEIPT = ", and --receipt with a receipt kept outside this file"
SELF_CONSISTENT_ONLY_1_0_0 = (
    "This shows only that the file is consistent with itself: anyone can recompute its "
    "content digest, and RMF schema 1.0.0 cannot carry a signature that shows who made it."
)

_EMBEDDED_KEY_ONLY = (
    "That shows only that whoever holds that key signed it; pass --trusted-key PUBFILE "
    "to check who signed."
)

# A schema error message quotes the failing value, which can be a whole register.
_MAX_SCHEMA_MESSAGE = 300


class UnsupportedRmfVersionError(ValueError):
    """The document declares an ``rmf_schema_version`` this RiskForge does not read."""

    def __init__(self, version: object) -> None:
        reads = ", ".join(sorted(SCHEMA_FILES))
        if isinstance(version, str):
            message = f"RMF schema version {version!r} is not one this RiskForge reads"
        elif version is None:
            message = "it declares no rmf_schema_version"
        else:
            message = f"its rmf_schema_version is a JSON {_json_type(version)}, not a string"
        super().__init__(f"{message} (it reads {reads}).")
        self.version = version


def _json_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    return {dict: "object", list: "array"}.get(type(value), type(value).__name__)


class RmfFileError(ValueError):
    """The file cannot be read, is not UTF-8 JSON, or its top level is not an object."""


def load_schema(version: str) -> dict[str, Any]:
    """The bundled JSON Schema for RMF schema ``version``.

    Raises
    ------
    UnsupportedRmfVersionError
        If RiskForge has no schema for ``version``.
    """
    if version not in SCHEMA_FILES:
        raise UnsupportedRmfVersionError(version)
    text = files("riskforge._data.schemas").joinpath(SCHEMA_FILES[version]).read_text("utf-8")
    schema: dict[str, Any] = json.loads(text)
    return schema


def content_digest(document: dict[str, Any]) -> str:
    """The SHA-256 a document's ``sha256_hash`` must equal, by its declared version.

    1.0.0: the whole document with ``sha256_hash``, ``audit_entry_hash`` and
    ``signed_by`` blanked, as 1.1.3 computed it. 1.1.0: the document without ``id``,
    ``generated_at``, ``sha256_hash`` and the provenance blocks, with ``signoffs`` read
    as ``[]`` when absent (ADR-04 section 2).

    Raises
    ------
    UnsupportedRmfVersionError
        If the document declares any other ``rmf_schema_version``.
    """
    version = document.get("rmf_schema_version")
    if version == "1.0.0":
        source = {**document, **dict.fromkeys(_BLANKED_1_0_0, "")}
    elif version == "1.1.0":
        source = {k: v for k, v in document.items() if k not in _NOT_DIGESTED_1_1_0}
        source.setdefault("signoffs", [])
    else:
        raise UnsupportedRmfVersionError(version)
    return sha256_hex(canonical_json(source))


def schema_errors(document: dict[str, Any], version: str) -> list[str]:
    """Each way ``document`` fails the bundled schema for ``version``, sorted.

    Each message starts with the JSON location of the failing value.

    Raises
    ------
    UnsupportedRmfVersionError
        If RiskForge has no schema for ``version``.
    """
    import jsonschema

    validator = jsonschema.Draft202012Validator(load_schema(version))
    messages = []
    for error in validator.iter_errors(document):
        where = "/".join(str(part) for part in error.absolute_path) or "top level"
        message = error.message
        if len(message) > _MAX_SCHEMA_MESSAGE:
            message = message[: _MAX_SCHEMA_MESSAGE - 3] + "..."
        messages.append(f"{where}: {message}")
    return sorted(messages)


@dataclass(frozen=True)
class RmfCheck:
    """What ``check_rmf_document`` found; ``findings`` empty means the file passed.

    ``notes`` say what was checked and what a pass proves, such as a signature verified
    only with the key embedded in the file. ``trusted_key_checked`` is whether trusted
    keys were given; a pass then means a trusted key signed the file. Without them a
    pass shows only that the file is consistent with itself, and the last note says so.
    ``verified`` is the rule ``riskforge verify --file`` uses to print "RMF integrity
    verified" rather than "RMF file is internally consistent".
    """

    version: str
    stored_digest: object
    computed_digest: str
    schema_errors: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    trusted_key_checked: bool = False

    @property
    def ok(self) -> bool:
        """True when nothing failed. Without trusted keys, only that the file is consistent."""
        return not self.findings

    @property
    def verified(self) -> bool:
        """True when nothing failed and the file was checked against trusted keys.

        A trusted key then signed the file, its sign-offs and its receipt. Without
        trusted keys this is False even when ``ok`` is True, since anyone can rebuild
        the chain proof, receipt and signatures of a file with a key of their own.
        """
        return self.ok and self.trusted_key_checked


def check_rmf_document(
    document: dict[str, Any],
    trusted_keys: Sequence[str] = (),
    receipts: Sequence[tuple[str, Receipt]] = (),
    *,
    trust_required: bool | None = None,
) -> RmfCheck:
    """Check a standalone RMF document as ADR-04 section 6 orders it, reporting every failure.

    Step 1 for every version: the document validates against the schema its
    ``rmf_schema_version`` names, and ``sha256_hash`` equals the content digest. For a
    1.1.0 document that validates, steps 2 to 7: ``public_keys``, the RMF signatures,
    the sign-offs, the chain proof, the embedded receipt, and each of ``receipts``
    (a label and a receipt read from its own file) against the chain proof.

    ``trusted_keys`` are base64 raw Ed25519 public keys. When given, the file must carry
    an RMF signature, and every RMF signature, sign-off and the embedded receipt must be
    signed by one of them, compared as raw bytes. A 1.0.0 document cannot carry a
    signature, so it fails when ``trust_required``, which defaults to whether
    ``trusted_keys`` or ``receipts`` were given.

    Raises
    ------
    UnsupportedRmfVersionError
        If ``rmf_schema_version`` is not a string naming a version RiskForge reads.
    ValueError
        If a trusted key is not 32 bytes of base64.
    """
    version = document.get("rmf_schema_version")
    if not isinstance(version, str) or version not in SCHEMA_FILES:
        raise UnsupportedRmfVersionError(version)
    trusted = list(trusted_keys)
    for key in trusted:
        decode_public_key(key)

    invalid = schema_errors(document, version)
    findings = [
        f"It does not validate against RMF schema {version}: {message}" for message in invalid
    ]
    stored = document.get("sha256_hash", "")
    computed = content_digest(document)
    if not stored:
        findings.append("It has no sha256_hash field to verify.")
    elif stored != computed:
        findings.append(
            "Its content does not match its SHA-256 digest. "
            f"Stored: {stored}; recomputed: {computed}."
        )
    notes: list[str] = []
    if trust_required is None:
        trust_required = bool(trusted or receipts)
    if version == "1.0.0":
        notes.append(
            "The file declares RMF schema 1.0.0, so only its schema and content digest "
            "were checked."
        )
        if trust_required:
            findings.append(RMF_1_0_0_CANNOT_BE_TRUSTED)
    elif invalid:
        findings.append(
            "Its public keys, signatures, sign-offs, chain proof and receipt were not checked, "
            "because it does not validate against its schema."
        )
    else:
        _Provenance(document, computed, trusted, findings, notes).check(receipts)
    if not trusted and not findings:
        if version == "1.0.0":
            notes.append(SELF_CONSISTENT_ONLY_1_0_0)
        else:
            notes.append(f"{SELF_CONSISTENT_ONLY}{'' if receipts else _AND_A_RECEIPT}.")
    return RmfCheck(
        version=version,
        stored_digest=stored,
        computed_digest=computed,
        schema_errors=invalid,
        findings=findings,
        notes=notes,
        trusted_key_checked=bool(trusted),
    )


class _Provenance:
    """ADR-04 section 6 steps 2 to 7 for a 1.1.0 document that validates against its schema.

    The schema has already fixed every field's type, the ``ed25519`` algorithm of each
    signature and key record, and that a chain proof entry with ``key_id`` has a
    ``signature`` and the reverse, so these steps check what a schema cannot.
    """

    def __init__(
        self,
        document: dict[str, Any],
        digest: str,
        trusted_keys: list[str],
        findings: list[str],
        notes: list[str],
    ) -> None:
        self.document = document
        self.digest = digest
        self.trusted_keys = trusted_keys
        self.trusted = {decode_public_key(key) for key in trusted_keys}
        self.findings = findings
        self.notes = notes
        self.system_id: str = document["register"]["system"]["id"]
        self.register_fingerprint = document_fingerprint(document["register"])
        self.keys: dict[str, str] = {}  # key id -> base64 public key, for records that passed
        self.refused: set[str] = set()
        # The seq of the chain proof entry that records the register in this file.
        self.register_seq: int | None = None

    def check(self, receipts: Sequence[tuple[str, Receipt]]) -> None:
        self._public_keys()
        self._rmf_signatures()
        self._signoffs()
        entries = self._chain_proof()
        if entries is None:
            self.findings.append(
                "The embedded receipt and any receipt files were not checked, because the "
                "chain proof could not be read."
            )
            return
        self._embedded_receipt(entries)
        for label, receipt in receipts:
            self._receipt_file(label, receipt, entries)

    def _trust(self, key: str) -> str:
        """`` (a trusted key)``, or an empty string when no trusted key was given."""
        return " (a trusted key)" if self.trusted and decode_public_key(key) in self.trusted else ""

    def _untrusted(self, key: str) -> bool:
        return bool(self.trusted) and decode_public_key(key) not in self.trusted

    def _public_keys(self) -> None:
        """Section 4 steps 1 and 2: unique key ids, each the key id of its own key."""
        records = self.document.get("public_keys", [])
        counts = Counter(record["key_id"] for record in records)
        for key_id, count in sorted(counts.items()):
            if count > 1:
                self.findings.append(
                    f"public_keys holds {count} records for key id {key_id}; it must hold one."
                )
                self.refused.add(key_id)
        for record in records:
            key_id, key = record["key_id"], record["public_key"]
            if key_id in self.refused:
                continue
            try:
                derived = key_id_for(key)
            except ValueError:
                derived = None
            if derived != key_id:
                self.findings.append(
                    f"public_keys record {key_id}: its key_id is not the key id of its public_key."
                )
                self.refused.add(key_id)
                continue
            self.keys[key_id] = key

    def _resolve(self, label: str, key_id: str) -> str | None:
        """Section 4 step 3: the key a ``key_id`` names, or None with a finding."""
        key = self.keys.get(key_id)
        if key is not None:
            return key
        if key_id in self.refused:
            self.findings.append(
                f"{label} names key id {key_id}, whose public_keys record is refused."
            )
        else:
            self.findings.append(
                f"{label} names key id {key_id}, which has no record in public_keys."
            )
        return None

    def _rmf_signatures(self) -> None:
        """Step 3: each RMF signature verifies over the content digest."""
        records = self.document.get("signatures", [])
        message = rmf_signing_message(self.digest)
        for number, record in enumerate(records, 1):
            label = f"RMF signature {number}"
            key_id = record["key_id"]
            key = self._resolve(label, key_id)
            if key is None:
                continue
            if not verify_signature(key, message, record["signature"]):
                self.findings.append(
                    f"{label} by {key_id} does not verify against the content digest."
                )
            elif self._untrusted(key):
                self.findings.append(f"{label} is by {key_id}, which is not a trusted key.")
            elif self.trusted:
                self.notes.append(f"{label} by {key_id} verifies with a trusted key.")
            else:
                self.notes.append(
                    f"{label} by {key_id} verifies with the public key embedded in the file. "
                    f"{_EMBEDDED_KEY_ONLY}"
                )
        if not records:
            if self.trusted:
                self.findings.append(
                    "A trusted key was given, but the file carries no RMF signature."
                )
            else:
                self.notes.append("The file is not signed.")

    def _signoffs(self) -> None:
        """Step 4: each sign-off verifies and is for the register this file holds."""
        from riskforge.models.rmf import SignOff

        for number, raw in enumerate(self.document.get("signoffs", []), 1):
            label = f"Sign-off {number}"
            try:
                signoff = SignOff.model_validate(raw)
            except ValidationError as exc:
                self.findings.append(
                    f"{label} is not a valid sign-off ({exc.error_count()} field error(s))."
                )
                continue
            before = len(self.findings)
            key = self._resolve(label, signoff.key_id)
            if key is not None:
                if not verify_signature(key, signoff_signing_message(signoff), signoff.signature):
                    self.findings.append(f"{label}: the signature does not verify.")
                elif self._untrusted(key):
                    self.findings.append(
                        f"{label} is signed by {signoff.key_id}, which is not a trusted key."
                    )
            if signoff.register_fingerprint != self.register_fingerprint:
                self.findings.append(
                    f"{label} is for register fingerprint {signoff.register_fingerprint}, not "
                    f"the register in this file ({self.register_fingerprint})."
                )
            if len(self.findings) == before and key is not None:
                said = (
                    f"{label}: {signoff.decision} by {signoff.approver} on version "
                    f"{signoff.version_number}, signed by {signoff.key_id}"
                )
                if self.trusted:
                    self.notes.append(f"{said} (a trusted key).")
                else:
                    self.notes.append(
                        f"{said} with the public key embedded in the file. {_EMBEDDED_KEY_ONLY}"
                    )

    def _chain_proof(self) -> list[AuditEntry] | None:
        """Step 5: links and hashes from seq 0, entry signatures, and the last fingerprint."""
        raw_entries = self.document["chain_proof"]["entries"]
        try:
            entries = [AuditEntry.model_validate(raw) for raw in raw_entries]
        except ValidationError as exc:
            self.findings.append(
                "The chain proof holds an entry that is not a valid audit entry "
                f"({exc.error_count()} field error(s))."
            )
            return None
        before = len(self.findings)
        try:
            self.findings.extend(verify_links(("Chain proof entry", entry) for entry in entries))
        except (ValueError, RecursionError):
            # A value nested too deeply for the serialiser; the strict reader refuses one
            # in a file, but a document can reach this function another way.
            self.findings.append(
                "The chain proof holds an entry that cannot be hashed, so its links and "
                "entry hashes were not checked."
            )
            return None
        for entry in entries:
            if entry.key_id is None or entry.signature is None:
                continue
            label = f"Chain proof entry seq {entry.seq}"
            key = self._resolve(label, entry.key_id)
            if key is not None and not verify_signature(
                key, entry_signing_message(entry.entry_hash), entry.signature
            ):
                self.findings.append(f"{label}: the signature by {entry.key_id} does not verify.")
        recorded = None
        for entry in entries:
            if entry.system_id == self.system_id and entry.register_fingerprint is not None:
                recorded = entry.register_fingerprint
                self.register_seq = entry.seq
        if recorded is None:
            self.findings.append(
                f"The chain proof records no register fingerprint for system {self.system_id}."
            )
        elif recorded != self.register_fingerprint:
            self.findings.append(
                "The register in this file is not the state the chain proof records last for "
                f"its system: the chain proof records {recorded}, the register block is "
                f"{self.register_fingerprint}."
            )
        if len(self.findings) == before:
            self.notes.append(
                f"Chain proof: {len(entries)} entries, seq {entries[0].seq} to "
                f"{entries[-1].seq}; its links and entry hashes check, and the last register "
                "fingerprint it records for the system is the register in this file."
            )
        return entries

    def _embedded_receipt(self, entries: list[AuditEntry]) -> None:
        """Step 6: the receipt names the last chain proof entry and this file's register."""
        label = "The embedded receipt"
        try:
            receipt = Receipt.model_validate(self.document["receipt"])
        except ValidationError as exc:
            self.findings.append(
                f"{label} is not a valid receipt ({exc.error_count()} field error(s))."
            )
            return
        before = len(self.findings)
        key = None
        if receipt.key_id is not None:
            key = self._resolve(label, receipt.key_id)
            if key is None:
                return
            # Section 4 step 4: the receipt's own public_key is the key of its record.
            if receipt.public_key is not None and decode_public_key(
                receipt.public_key
            ) != decode_public_key(key):
                self.findings.append(
                    f"{label}: its public_key differs from the public_keys record for its key_id."
                )
                return
        self.findings.extend(
            check_receipt(
                receipt, entries, self.trusted_keys, label=label, chain_name="the chain proof"
            )
        )
        last = entries[-1]
        if receipt.seq != last.seq:
            self.findings.append(
                f"{label} names seq {receipt.seq}, but the last chain proof entry is seq "
                f"{last.seq}."
            )
        elif receipt.entry_hash != last.entry_hash:
            self.findings.append(
                f"{label} names entry_hash {receipt.entry_hash}, but the last chain proof "
                f"entry has {last.entry_hash}."
            )
        if receipt.system_id != self.system_id:
            self.findings.append(
                f"{label} is for system {receipt.system_id}, not this file's system "
                f"{self.system_id}."
            )
        if receipt.register_fingerprint != self.register_fingerprint:
            self.findings.append(
                f"{label}'s register_fingerprint is {receipt.register_fingerprint or 'null'}, "
                f"not the fingerprint of the register in this file ({self.register_fingerprint})."
            )
        if len(self.findings) == before:
            signer = (
                f", signed by {receipt.key_id}{self._trust(key)}"
                if key is not None
                else ", not signed"
            )
            self.notes.append(
                f"{label} names the last chain proof entry (seq {receipt.seq}) and the "
                f"register in this file{signer}."
            )

    def _receipt_file(self, label: str, receipt: Receipt, entries: list[AuditEntry]) -> None:
        """Step 7: a receipt read from its own file holds against the chain proof."""
        errors = check_receipt(
            receipt, entries, self.trusted_keys, label=label, chain_name="the chain proof"
        )
        if errors:
            self.findings.extend(errors)
            return
        if receipt.key_id is None:
            signer = ", not signed"
        else:
            signer = f", signed by {receipt.key_id}"
            if self.trusted:
                signer += " (a trusted key)"
        self.notes.append(f"{label}: the chain proof holds its entry at seq {receipt.seq}{signer}.")
        if self.register_seq is not None and self.register_seq > receipt.seq:
            after = sum(1 for entry in entries if entry.seq > receipt.seq)
            entries_after = "entry comes" if after == 1 else "entries come"
            self.notes.append(
                f"{label} does not cover the register in this file: the chain proof records "
                f"it at seq {self.register_seq}, after the receipt's seq {receipt.seq}, and "
                f"{after} chain proof {entries_after} after it. A receipt covers only the "
                "entries up to its seq."
            )


def rmf_signing_message(digest: str) -> bytes:
    """What an RMF signature signs: the domain prefix and the hex content digest."""
    return RMF_SIGNING_DOMAIN + digest.encode("ascii")


def signoff_signing_message(signoff: SignOff) -> bytes:
    """What a sign-off's signature signs: every field but ``signature``, in JSON mode.

    Every field is present, so a sign-off made without a comment and one with ``""``
    give the same message, and ``key_id`` is signed.
    """
    body = signoff.model_dump(mode="json", exclude={"signature"})
    return SIGNOFF_SIGNING_DOMAIN + canonical_json(body)


def read_rmf_file(path: Path) -> dict[str, Any]:
    """Read an RMF file as ADR-04 section 2 requires.

    Raises
    ------
    RmfFileError
        If the file cannot be read, is not UTF-8 JSON, or its top level is not an object.
    StrictJsonError
        If it holds a duplicate key or a non-finite number, which RiskForge never writes.
    NumberTooLongError
        If it holds an integer with more digits than Python reads, which RiskForge never
        writes either.
    """
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise RmfFileError(f"it cannot be read: {exc.strerror or exc}.") from exc
    except UnicodeDecodeError as exc:
        raise RmfFileError("it is binary, not JSON; verify the .json export.") from exc
    try:
        data = loads_strict(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RmfFileError(f"it is not JSON ({exc}).") from exc
    if not isinstance(data, dict):
        raise RmfFileError("its top level is not a JSON object.")
    return data
