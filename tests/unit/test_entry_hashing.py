"""Entry hashing keeps 1.1.3 hashes and records register fingerprints (ADR-03, PRD-332)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from riskforge.engine.audit import AuditEngine
from riskforge.engine.risk import RiskEngine
from riskforge.engine.system import SystemEngine
from riskforge.integrity.canonical import (
    UnfingerprintableDocumentError,
    canonical_json,
    document_fingerprint,
)
from riskforge.integrity.chain import (
    GENESIS_PREV_HASH,
    compute_entry_hash,
    entry_signing_message,
    entry_to_dict,
    verify_links,
)
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.models.system import AISystem, AnnexIIICategory
from riskforge.storage.filesystem import FileStore

V113_LOG = Path(__file__).resolve().parents[1] / "fixtures" / "v1_1_3_project" / "audit.jsonl"


def _v113_hash(stored: dict) -> str:
    """The hash RiskForge 1.1.3 computed, over the entry dict as it stored it."""
    data = dict(stored)
    data["entry_hash"] = ""
    canonical = json.dumps(
        {"prev_hash": stored["prev_hash"], **data}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry(**extra: object) -> AuditEntry:
    return AuditEntry(
        seq=0,
        event="e",
        timestamp=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        actor=AuditActor(type="human", identity="t"),
        system_id="s",
        payload={"k": None},
        prev_hash=GENESIS_PREV_HASH,
        **extra,
    )


def _item(title: str = "r") -> RiskItem:
    return RiskItem(
        dimension=RiskDimension.privacy,
        title=title,
        description="d",
        likelihood=Likelihood(2),
        severity=Severity(2),
        residual_likelihood=Likelihood(2),
        residual_severity=Severity(2),
    )


async def _project(tmp_path: Path) -> tuple[FileStore, AuditEngine, str]:
    store = FileStore(tmp_path)
    await store.init_project("p", {})
    audit = AuditEngine(store, AuditActor(type="human", identity="t"))
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    await SystemEngine(store, audit).create(system)
    return store, audit, str(system.id)


def test_every_entry_written_by_v113_hashes_to_its_stored_value() -> None:
    lines = V113_LOG.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 17
    for line in lines:
        entry = AuditEntry.model_validate(json.loads(line))
        assert compute_entry_hash(entry) == entry.entry_hash, entry.seq
        assert entry_to_dict(entry) == json.loads(line), entry.seq


def test_v113_style_entry_with_a_null_payload_value_hashes_as_before() -> None:
    stored = {
        "seq": 0,
        "event": "system.classified",
        "timestamp": "2026-10-12T09:00:00.123456Z",
        "actor": {"type": "human", "identity": "cli"},
        "system_id": "1a28b6ac-0000-4000-8000-000000000000",
        "payload": {"annex_iii_self_classification_documented": True, "annex_iii_category": None},
        "prev_hash": GENESIS_PREV_HASH,
        "entry_hash": "",
    }
    stored["entry_hash"] = _v113_hash(stored)
    entry = AuditEntry.model_validate(stored)
    assert compute_entry_hash(entry) == stored["entry_hash"]
    assert entry_to_dict(entry) == stored
    assert entry_to_dict(entry)["payload"]["annex_iii_category"] is None


def test_storage_form_omits_absent_optional_fields() -> None:
    data = entry_to_dict(_entry())
    assert not {"register_fingerprint", "key_id", "signature"} & set(data)
    assert data["payload"] == {"k": None}


def test_fingerprint_and_key_id_are_hashed_and_the_signature_is_not() -> None:
    base = compute_entry_hash(_entry())
    with_fingerprint = _entry(register_fingerprint="a" * 64)
    assert entry_to_dict(with_fingerprint)["register_fingerprint"] == "a" * 64
    assert compute_entry_hash(with_fingerprint) != base
    assert compute_entry_hash(_entry(key_id="ed25519:0123456789abcdef")) != base
    assert compute_entry_hash(_entry(signature="c2lnbmF0dXJl")) == base


def test_prev_hash_is_hashed_as_stored() -> None:
    assert compute_entry_hash(_entry()) != compute_entry_hash(
        _entry().model_copy(update={"prev_hash": "f" * 64})
    )


def test_signing_message_is_domain_separated() -> None:
    assert entry_signing_message("ab12") == b"riskforge.audit-entry.v1\nab12"


def test_verify_links_reports_gaps_broken_links_and_bad_hashes() -> None:
    first = _entry()
    first.entry_hash = compute_entry_hash(first)
    second = _entry().model_copy(update={"seq": 2, "prev_hash": "x"})
    second.entry_hash = "bad"
    errors = verify_links([("Line 1", first), ("Line 2", second)])
    assert any("sequence gap" in error for error in errors)
    assert any("prev_hash mismatch" in error for error in errors)
    assert any("entry_hash mismatch" in error for error in errors)
    assert verify_links([("Line 1", first)]) == []


@pytest.mark.parametrize(
    "document",
    [
        {"a": date(2026, 10, 12)},
        {"a": b"bytes"},
        {"a": {"x"}},
        {1: "x", "b": "y"},
    ],
    ids=["date", "binary", "set", "mixed-keys"],
)
def test_unencodable_documents_raise_a_typed_error(document: dict) -> None:
    with pytest.raises(UnfingerprintableDocumentError):
        document_fingerprint(document)


def test_canonical_json_matches_v113_settings() -> None:
    assert canonical_json({"b": 1, "a": "é"}) == b'{"a":"\\u00e9","b":1}'


async def test_each_entry_records_the_stored_register_fingerprint(tmp_path: Path) -> None:
    store, audit, sid = await _project(tmp_path)
    engine = RiskEngine(store, audit)
    await engine.create_register(sid, "A", "B")
    created = await store.read_last_audit_entry()
    item = await engine.add_risk(sid, _item())
    await engine.add_mitigation(
        sid,
        str(item.id),
        Mitigation(
            description="Quarterly bias audit",
            control_type="detective",
            owner="Risk lead",
            status="planned",
        ),
    )
    await engine.accept_risk(sid, str(item.id), "Residual risk is low.", "t")
    entries = [entry async for entry in store.read_audit()]
    assert entries[0].event == "system.created"
    assert entries[0].register_fingerprint is None
    assert all(entry.register_fingerprint for entry in entries[1:])
    document = await store.read_register_document(sid)
    assert entries[-1].register_fingerprint == document_fingerprint(document)
    assert created.register_fingerprint != entries[-1].register_fingerprint


async def test_classify_register_rewrite_carries_a_fingerprint(tmp_path: Path) -> None:
    store, audit, sid = await _project(tmp_path)
    await RiskEngine(store, audit).create_register(sid, "A", "B")
    before = (await store.read_last_audit_entry()).register_fingerprint
    await SystemEngine(store, audit).classify(sid, AnnexIIICategory.employment)
    entry = await store.read_last_audit_entry()
    assert entry.event == "system.classified"
    assert entry.register_fingerprint == document_fingerprint(
        await store.read_register_document(sid)
    )
    assert entry.register_fingerprint != before


async def test_the_writer_fingerprints_the_yaml_text_it_wrote(tmp_path: Path) -> None:
    # U+0085 does not survive a YAML round trip (it reads back as a space), so a
    # fingerprint of the dumped dict would never match the stored register.
    store, audit, sid = await _project(tmp_path)
    engine = RiskEngine(store, audit)
    await engine.create_register(sid, "A", "B")
    await engine.add_risk(sid, _item("line\x85break"))
    entry = await store.read_last_audit_entry()
    document = await store.read_register_document(sid)
    assert document["items"][0]["title"] != "line\x85break"
    assert entry.register_fingerprint == document_fingerprint(document)
