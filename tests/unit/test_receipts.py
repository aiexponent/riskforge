"""Receipts: signing message, chain check, key resolution and file reading (ADR-04 sections 2, 4, 5)."""

from __future__ import annotations

import base64
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from riskforge.integrity.canonical import canonical_json
from riskforge.integrity.receipts import (
    InvalidReceiptError,
    ReceiptFileError,
    build_receipt,
    check_receipt,
    read_receipt_file,
    receipt_from_document,
    receipt_signing_message,
    receipt_to_dict,
    write_receipt_file,
)
from riskforge.integrity.signing import Ed25519Signer, generate_key_pair_pem
from riskforge.models import Receipt
from riskforge.models.audit import AuditActor, AuditEntry

posix_only = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")


def _signer() -> Ed25519Signer:
    private_pem, _ = generate_key_pair_pem()
    return Ed25519Signer.from_pem(private_pem, Path("k.pem"))


def _head(
    seq: int = 4,
    entry_hash: str = "a" * 64,
    fingerprint: str | None = None,
    system_id: str = "s",
) -> AuditEntry:
    return AuditEntry(
        seq=seq,
        event="risk_item.added",
        actor=AuditActor(type="human", identity="t"),
        system_id=system_id,
        prev_hash="0" * 64,
        entry_hash=entry_hash,
        timestamp=datetime(2026, 10, 1, tzinfo=UTC),
        register_fingerprint=fingerprint,
    )


def _noncanonical_spelling(public_key_b64: str) -> str:
    """Another base64 text that decodes, strictly, to the same 32 bytes.

    32 bytes take 43 characters and one ``=``; the last character carries 4 unused bits.
    """
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    last = alphabet.index(public_key_b64[42])
    spelled = public_key_b64[:42] + alphabet[last | 0b0001] + "="
    if spelled == public_key_b64:
        spelled = public_key_b64[:42] + alphabet[last | 0b0010] + "="
    assert base64.b64decode(spelled, validate=True) == base64.b64decode(public_key_b64)
    return spelled


def test_signing_message_is_the_prefix_and_canonical_json_without_key_and_signature() -> None:
    signer = _signer()
    receipt = build_receipt(_head(), "s", "f" * 64, signer)
    body = receipt.model_dump(mode="json", exclude={"public_key", "signature"})
    assert body["key_id"] == signer.key_id  # the key id is signed
    assert receipt_signing_message(receipt) == b"riskforge.receipt.v1\n" + canonical_json(body)
    moved = receipt.model_copy(update={"public_key": "x", "signature": "y"})
    assert receipt_signing_message(moved) == receipt_signing_message(receipt)


def test_receipt_records_the_head_and_the_fingerprint() -> None:
    head = _head(seq=7, entry_hash="b" * 64)
    receipt = build_receipt(head, "s", None)
    assert (receipt.receipt_version, receipt.system_id, receipt.seq) == ("1", "s", 7)
    assert receipt.entry_hash == "b" * 64
    assert receipt.register_fingerprint is None
    assert receipt.issued_at.tzinfo is not None
    data = receipt_to_dict(receipt)
    assert data["register_fingerprint"] is None  # always present, null when unknown
    assert not {"key_id", "public_key", "signature"} & set(data)  # only when signed
    assert receipt_from_document(data) == receipt


def test_receipt_matches_the_chain_that_holds_its_entry() -> None:
    head = _head()
    receipt = build_receipt(head, "s", None)
    assert check_receipt(receipt, [_head(seq=3, entry_hash="c" * 64), head]) == []
    truncated = check_receipt(receipt, [_head(seq=3, entry_hash="c" * 64)])
    assert len(truncated) == 1 and "truncated or replaced" in truncated[0]
    rewritten = check_receipt(receipt, [_head(entry_hash="d" * 64)])
    assert len(rewritten) == 1 and "rewritten" in rewritten[0]


def test_signed_receipt_verifies_with_a_trusted_key() -> None:
    signer = _signer()
    head = _head(fingerprint="f" * 64)
    receipt = build_receipt(head, "s", "f" * 64, signer)
    assert receipt.key_id == signer.key_id and receipt.public_key == signer.public_key_b64
    assert check_receipt(receipt, [head]) == []
    assert check_receipt(receipt, [head], [signer.public_key_b64]) == []
    assert check_receipt(receipt, [head], [_signer().public_key_b64, signer.public_key_b64]) == []


def test_altered_signed_receipt_fails() -> None:
    signer = _signer()
    head = _head()
    receipt = build_receipt(head, "s", "f" * 64, signer)
    for update in ({"seq": 3}, {"register_fingerprint": None}, {"system_id": "t"}):
        edited = receipt.model_copy(update=update)
        assert any("signature does not verify" in e for e in check_receipt(edited, [head]))


def test_receipt_fingerprint_must_be_the_latest_the_chain_records_for_its_system() -> None:
    entries = [
        _head(seq=0, entry_hash="0" * 64, fingerprint="1" * 64),
        _head(seq=1, entry_hash="b" * 64, fingerprint="2" * 64, system_id="t"),
        _head(seq=2, entry_hash="c" * 64, fingerprint="3" * 64),
        _head(seq=3, entry_hash="d" * 64, system_id="t"),
        _head(seq=4, entry_hash="a" * 64, fingerprint="9" * 64),  # after the receipt's seq
    ]
    assert check_receipt(build_receipt(entries[3], "s", "3" * 64), entries) == []
    assert check_receipt(build_receipt(entries[3], "t", "2" * 64), entries) == []
    for system_id, fingerprint in (
        ("s", "1" * 64),  # an earlier fingerprint of the system
        ("s", "9" * 64),  # one recorded only after the receipt's seq
        ("s", None),  # the chain records one, the receipt none
        ("t", "3" * 64),  # another system's fingerprint
        ("u", "3" * 64),  # a system the chain records nothing for
    ):
        errors = check_receipt(build_receipt(entries[3], system_id, fingerprint), entries)
        assert len(errors) == 1, (system_id, fingerprint, errors)
        assert "register fingerprint" in errors[0] and system_id in errors[0]


def test_receipt_and_chain_without_fingerprints_match() -> None:
    head = _head()
    assert check_receipt(build_receipt(head, "u", None), [head]) == []


def test_signed_receipt_from_an_untrusted_key_fails() -> None:
    head = _head()
    receipt = build_receipt(head, "s", None, _signer())
    errors = check_receipt(receipt, [head], [_signer().public_key_b64])
    assert len(errors) == 1 and "not a trusted key" in errors[0]


def test_unsigned_receipt_fails_when_a_trusted_key_is_required() -> None:
    head = _head()
    errors = check_receipt(build_receipt(head, "s", None), [head], [_signer().public_key_b64])
    assert len(errors) == 1 and "not signed" in errors[0]


def test_receipt_key_is_its_own_public_key_and_must_match_its_key_id() -> None:
    signer, other = _signer(), _signer()
    head = _head()
    receipt = build_receipt(head, "s", None, signer)
    swapped = receipt.model_copy(update={"public_key": other.public_key_b64})
    assert any("key_id does not match" in e for e in check_receipt(swapped, [head]))
    # Re-signed by another key but still naming the first key's id: refused.
    forged = receipt.model_copy(update={"public_key": other.public_key_b64})
    forged = forged.model_copy(update={"signature": other.sign(receipt_signing_message(forged))})
    assert check_receipt(forged, [head])


@pytest.mark.parametrize(
    "update",
    [
        {"signature": None},
        {"public_key": None},
        {"key_id": None},
        {"public_key": base64.b64encode(b"\x01" * 31).decode()},
        {"public_key": "not base64!"},
        {"signature": base64.b64encode(b"\x01" * 63).decode()},
    ],
)
def test_incomplete_or_malformed_signing_fields_fail(update: dict) -> None:
    head = _head()
    receipt = build_receipt(head, "s", None, _signer()).model_copy(update=update)
    assert check_receipt(receipt, [head])


def test_trust_compares_the_raw_key_bytes_not_the_base64_text() -> None:
    signer = _signer()
    head = _head()
    receipt = build_receipt(head, "s", None, signer)
    respelled = receipt.model_copy(
        update={"public_key": _noncanonical_spelling(signer.public_key_b64)}
    )
    assert check_receipt(respelled, [head], [signer.public_key_b64]) == []
    trusted_respelled = _noncanonical_spelling(signer.public_key_b64)
    assert check_receipt(receipt, [head], [trusted_respelled]) == []


def test_receipt_document_must_hold_exactly_the_receipt_fields() -> None:
    data = receipt_to_dict(build_receipt(_head(), "s", None))
    with pytest.raises(InvalidReceiptError):
        receipt_from_document({**data, "note": "extra"})
    with pytest.raises(InvalidReceiptError):
        receipt_from_document({**data, "seq": "4"})  # no type coercion
    with pytest.raises(InvalidReceiptError):
        receipt_from_document({k: v for k, v in data.items() if k != "entry_hash"})
    with pytest.raises(ReceiptFileError, match="receipt_version"):
        receipt_from_document({**data, "receipt_version": "2"})
    with pytest.raises(ReceiptFileError):
        receipt_from_document({"hello": "world"})


def _rmf_with(receipt: Receipt, public_keys: list[dict]) -> dict:
    return {
        "rmf_schema_version": "1.1.0",
        "receipt": receipt_to_dict(receipt),
        "public_keys": public_keys,
    }


def _record(signer: Ed25519Signer) -> dict:
    return {"key_id": signer.key_id, "algorithm": "ed25519", "public_key": signer.public_key_b64}


def test_receipt_is_read_from_an_rmf_and_its_key_resolved_through_public_keys() -> None:
    signer = _signer()
    receipt = build_receipt(_head(), "s", "f" * 64, signer)
    assert receipt_from_document(_rmf_with(receipt, [_record(signer)])) == receipt
    unsigned = build_receipt(_head(), "s", "f" * 64)
    assert receipt_from_document(_rmf_with(unsigned, [])) == unsigned


@pytest.mark.parametrize(
    ("records", "message"),
    [
        (lambda s, o: [], "no record"),
        (lambda s, o: [_record(o)], "no record"),
        (lambda s, o: [_record(s), _record(s)], "two records"),
        (lambda s, o: [{**_record(s), "algorithm": "rsa"}], "algorithm"),
        (lambda s, o: [{**_record(o), "key_id": s.key_id}], "key id"),
        (lambda s, o: [{**_record(s), "public_key": "AAAA"}], "32 bytes"),
    ],
)
def test_rmf_key_resolution_failures(records, message: str) -> None:
    signer, other = _signer(), _signer()
    receipt = build_receipt(_head(), "s", "f" * 64, signer)
    with pytest.raises(InvalidReceiptError, match=message):
        receipt_from_document(_rmf_with(receipt, records(signer, other)))


def test_embedded_receipt_public_key_must_equal_its_record() -> None:
    signer, other = _signer(), _signer()
    receipt = build_receipt(_head(), "s", "f" * 64, signer)
    receipt = receipt.model_copy(update={"public_key": other.public_key_b64})
    with pytest.raises(InvalidReceiptError, match="public_key"):
        receipt_from_document(_rmf_with(receipt, [_record(signer)]))


def test_rmf_without_a_usable_receipt() -> None:
    with pytest.raises(InvalidReceiptError, match="no receipt"):
        receipt_from_document({"rmf_schema_version": "1.1.0", "public_keys": []})
    with pytest.raises(InvalidReceiptError, match="RMF schema 1.0.0 cannot carry a signature"):
        receipt_from_document({"rmf_schema_version": "1.0.0", "sha256_hash": "x"})
    with pytest.raises(ReceiptFileError, match="9.9.9"):
        receipt_from_document({"rmf_schema_version": "9.9.9"})


def test_receipt_file_round_trip_mode_and_no_overwrite(tmp_path: Path) -> None:
    receipt = build_receipt(_head(), "s", "f" * 64, _signer())
    path = tmp_path / "receipt.json"
    write_receipt_file(path, receipt)
    assert read_receipt_file(path) == receipt
    assert json.loads(path.read_text(encoding="utf-8")) == receipt_to_dict(receipt)
    before = path.read_bytes()
    with pytest.raises(ReceiptFileError, match="already exists"):
        write_receipt_file(path, build_receipt(_head(seq=5), "s", None))
    assert path.read_bytes() == before
    with pytest.raises(ReceiptFileError):
        write_receipt_file(tmp_path / "missing" / "r.json", receipt)


@posix_only
def test_receipt_file_is_created_with_mode_600(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    old = os.umask(0)
    try:
        write_receipt_file(path, build_receipt(_head(), "s", None))
    finally:
        os.umask(old)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "text",
    [
        '{"receipt_version": "1", "seq": 4, "seq": 3}',
        '{"rmf_schema_version": "1.1.0", "receipt": {"seq": 1, "seq": 2}}',
        '{"receipt_version": "1", "seq": NaN}',
        '{"receipt_version": "1", "seq": 1e400}',
    ],
)
def test_receipt_file_with_a_duplicate_key_or_non_finite_number_is_invalid(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / "r.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidReceiptError):
        read_receipt_file(path)


def test_receipt_file_with_a_seq_too_long_for_python_cannot_be_read(tmp_path: Path) -> None:
    data = receipt_to_dict(build_receipt(_head(), "s", None))
    text = json.dumps(data).replace('"seq": 4', '"seq": ' + "9" * 5000)
    path = tmp_path / "r.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(InvalidReceiptError, match="too long"):
        read_receipt_file(path)


@pytest.mark.parametrize("seq", [2**63, 10**100, -1])
def test_receipt_seq_must_be_a_bounded_non_negative_integer(seq: int) -> None:
    data = receipt_to_dict(build_receipt(_head(), "s", None))
    with pytest.raises(InvalidReceiptError, match="seq"):
        receipt_from_document({**data, "seq": seq})


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe binary", b"[1, 2]"])
def test_receipt_file_that_is_not_a_json_object_cannot_be_read(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "r.json"
    path.write_bytes(content)
    with pytest.raises(ReceiptFileError):
        read_receipt_file(path)
