"""Signed audit entries: AuditEngine with a signer, and check_integrity with trusted keys.

ADR-03 section 2 fixes the fields (``key_id`` inside the hash, ``signature`` outside it)
and ADR-04 section 4 the rule that an entry with one and not the other fails.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from riskforge.engine.audit import AuditEngine
from riskforge.engine.integrity import check_integrity, check_integrity_settled
from riskforge.engine.risk import RiskEngine
from riskforge.engine.system import SystemEngine
from riskforge.integrity.chain import compute_entry_hash, entry_signing_message
from riskforge.integrity.signing import Ed25519Signer, generate_key_pair_pem, verify_signature
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.system import AISystem
from riskforge.storage.filesystem import FileStore

ACTOR = AuditActor(type="api", identity="server")


def _signer() -> Ed25519Signer:
    private_pem, _ = generate_key_pair_pem()
    return Ed25519Signer.from_pem(private_pem, Path("k.pem"))


async def _project(tmp_path: Path, signer: Ed25519Signer | None) -> FileStore:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    audit = AuditEngine(store, ACTOR, signer=signer)
    system = AISystem(name="S", version="1", purpose="credit scoring", provider_name="P")
    await SystemEngine(store, audit).create(system)
    await RiskEngine(store, audit).create_register(str(system.id), "A", "B")
    return store


def _log(project: Path) -> Path:
    return project / ".riskforge" / "audit.jsonl"


def _lines(project: Path) -> list[dict]:
    return [json.loads(line) for line in _log(project).read_text().splitlines()]


def _write_lines(project: Path, lines: list[dict]) -> None:
    _log(project).write_text("".join(json.dumps(line) + "\n" for line in lines))


async def test_engine_signs_every_entry_hash_with_key_id_inside_the_hash(tmp_path: Path) -> None:
    signer = _signer()
    await _project(tmp_path, signer)
    lines = _lines(tmp_path)
    assert len(lines) >= 2
    for line in lines:
        entry = AuditEntry.model_validate(line)
        assert entry.key_id == signer.key_id
        assert compute_entry_hash(entry) == entry.entry_hash
        unkeyed = entry.model_copy(update={"key_id": None})
        assert compute_entry_hash(unkeyed) != entry.entry_hash  # key_id is hashed
        assert verify_signature(
            signer.public_key_b64, entry_signing_message(entry.entry_hash), entry.signature
        )


async def test_engine_without_a_signer_writes_no_key_or_signature(tmp_path: Path) -> None:
    await _project(tmp_path, None)
    assert not any({"key_id", "signature"} & set(line) for line in _lines(tmp_path))


async def test_signed_entries_pass_with_the_trusted_key(tmp_path: Path) -> None:
    signer = _signer()
    store = await _project(tmp_path, signer)
    report = await check_integrity(store, trusted_keys=[signer.public_key_b64])
    assert report.ok, report.errors
    assert not report.warnings
    settled = await check_integrity_settled(store, trusted_keys=[signer.public_key_b64])
    assert settled.ok, settled.errors


async def test_signed_entries_without_keys_pass_with_a_warning(tmp_path: Path) -> None:
    store = await _project(tmp_path, _signer())
    report = await check_integrity(store)
    assert report.ok, report.errors
    assert any("not checked" in w for w in report.warnings)
    assert not report.strict().ok


async def test_signed_entries_from_a_key_outside_the_trusted_set_fail(tmp_path: Path) -> None:
    store = await _project(tmp_path, _signer())
    report = await check_integrity(store, trusted_keys=[_signer().public_key_b64])
    assert not report.ok
    assert all("not a trusted key" in e for e in report.errors)
    assert len(report.errors) == len(_lines(tmp_path))


async def test_a_signature_that_does_not_verify_fails(tmp_path: Path) -> None:
    signer = _signer()
    store = await _project(tmp_path, signer)
    lines = _lines(tmp_path)
    raw = bytearray(base64.b64decode(lines[0]["signature"]))
    raw[0] ^= 0x01
    lines[0]["signature"] = base64.b64encode(bytes(raw)).decode("ascii")
    _write_lines(tmp_path, lines)  # the signature is outside the hash, so the chain holds
    report = await check_integrity(store, trusted_keys=[signer.public_key_b64])
    assert len(report.errors) == 1
    assert "seq 0" in report.errors[0] and "does not verify" in report.errors[0]


async def test_key_id_without_signature_fails_even_without_keys(tmp_path: Path) -> None:
    store = await _project(tmp_path, _signer())
    lines = _lines(tmp_path)
    del lines[-1]["signature"]
    _write_lines(tmp_path, lines)
    report = await check_integrity(store)
    assert len(report.errors) == 1
    assert "key_id" in report.errors[0] and "signature" in report.errors[0]


async def test_signature_without_key_id_fails_even_without_keys(tmp_path: Path) -> None:
    store = await _project(tmp_path, None)
    lines = _lines(tmp_path)
    lines[-1]["signature"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    _write_lines(tmp_path, lines)
    report = await check_integrity(store)
    assert len(report.errors) == 1
    assert "key_id" in report.errors[0] and "signature" in report.errors[0]


async def test_unsigned_entries_pass_with_trusted_keys(tmp_path: Path) -> None:
    store = await _project(tmp_path, None)
    report = await check_integrity(store, trusted_keys=[_signer().public_key_b64])
    assert report.ok, report.errors
