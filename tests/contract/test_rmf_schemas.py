"""RMF schemas 1.0.0 and 1.1.0, the content digest and the signing messages (ADR-04 sections 1, 2, 4).

A file written by 1.1.3 still validates against 1.0.0 and still matches its digest. New
documents are 1.1.0, carry no ``signed_by`` or ``audit_entry_hash``, and every provenance
object refuses a field ADR-04 does not define.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest
from riskforge.integrity.canonical import canonical_json, sha256_hex
from riskforge.integrity.receipts import build_receipt
from riskforge.integrity.rmf import (
    SCHEMA_FILES,
    RmfFileError,
    UnsupportedRmfVersionError,
    content_digest,
    load_schema,
    read_rmf_file,
    rmf_signing_message,
    signoff_signing_message,
)
from riskforge.integrity.signing import Ed25519Signer, generate_key_pair_pem
from riskforge.integrity.strict_json import StrictJsonError
from riskforge.models.audit import AuditActor, AuditEntry
from riskforge.models.register import RiskRegister
from riskforge.models.risk import Likelihood, Mitigation, RiskDimension, RiskItem, Severity
from riskforge.models.rmf import (
    RMF_SCHEMA_VERSION,
    ChainProof,
    PublicKeyRecord,
    RiskManagementFile,
    RmfSignature,
    SignOff,
    rmf_document,
)
from riskforge.models.system import AISystem

V113_RMF = Path(__file__).resolve().parents[1] / "fixtures" / "v1_1_3_project" / "rmf.json"
PUBLISHED = {
    "1.0.0": "https://aiexponent.com/schemas/riskforge/rmf/1.0.0.json",
    "1.1.0": "https://aiexponent.com/schemas/riskforge/rmf/1.1.0.json",
}
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _signer() -> Ed25519Signer:
    private_pem, _ = generate_key_pair_pem()
    return Ed25519Signer.from_pem(private_pem, Path("k.pem"))


def _register() -> RiskRegister:
    from riskforge.models.requirements import TestRequirement

    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    item = RiskItem(
        dimension=RiskDimension.discrimination,
        title="Bias",
        description="Desc.",
        likelihood=Likelihood.likely,
        severity=Severity.major,
        residual_likelihood=Likelihood.unlikely,
        residual_severity=Severity.minor,
        accepted=True,
        accepted_by="Jane Doe",
        mitigations=[
            Mitigation(
                description="Block release above a 0.10 parity gap",
                control_type="preventive",
                owner="ML team",
                status="implemented",
                recorded_by="Sam Lee",
            )
        ],
    )
    return RiskRegister(
        system=system,
        assessor_name="A",
        assessor_role="B",
        assessment_date=NOW,
        review_date=NOW + timedelta(days=365),
        items=[item],
        test_requirements=[
            TestRequirement(
                risk_item_id=item.id,
                description="Parity gap",
                metric_type="demographic_parity",
                threshold_range="<= 0.10",
                article_ref="Art.9(2)(a)",
            )
        ],
    )


def _rmf() -> RiskManagementFile:
    rmf = RiskManagementFile(register=_register())
    rmf.sha256_hash = content_digest(rmf_document(rmf))
    return rmf


def _entry(seq: int, prev_hash: str, **extra: object) -> AuditEntry:
    return AuditEntry(
        seq=seq,
        event="risk_item.added",
        timestamp=NOW,
        actor=AuditActor(type="human", identity="t"),
        system_id="s",
        prev_hash=prev_hash,
        entry_hash=f"{seq + 1:x}" * 64,
        **extra,
    )


def _signoff(signer: Ed25519Signer) -> SignOff:
    unsigned = SignOff(
        approver="Head of AI",
        decision="approved",
        version_number=1,
        register_fingerprint="f" * 64,
        totp_verified_at=NOW,
        signed_at=NOW,
        key_id=signer.key_id,
        signature="",
    )
    return unsigned.model_copy(update={"signature": signer.sign(signoff_signing_message(unsigned))})


def _full_rmf() -> RiskManagementFile:
    """Every provenance block filled, as a signed RiskForge Team export would carry them."""
    signer = _signer()
    rmf = _rmf()
    rmf.signoffs = [_signoff(signer)]
    rmf.sha256_hash = content_digest(rmf_document(rmf))
    entries = [
        _entry(0, "0000000000", register_fingerprint="e" * 64),
        _entry(1, "1" * 64, key_id=signer.key_id, signature=signer.sign(b"x")),
    ]
    rmf.chain_proof = ChainProof(scope="project", entries=entries)
    rmf.receipt = build_receipt(entries[-1], "s", "e" * 64, signer)
    rmf.signatures = [
        RmfSignature(
            key_id=signer.key_id,
            signed_at=NOW,
            signature=signer.sign(rmf_signing_message(rmf.sha256_hash)),
        )
    ]
    rmf.public_keys = [PublicKeyRecord(key_id=signer.key_id, public_key=signer.public_key_b64)]
    return rmf


# --- the two schemas -----------------------------------------------------------------


@pytest.mark.parametrize("version", sorted(SCHEMA_FILES))
def test_schema_is_valid_and_its_id_is_the_published_url(version: str) -> None:
    schema = load_schema(version)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"] == PUBLISHED[version]


def test_schema_files_are_named_by_version() -> None:
    assert SCHEMA_FILES == {"1.0.0": "rmf-1.0.0.schema.json", "1.1.0": "rmf-1.1.0.schema.json"}


def test_unknown_schema_version_is_refused() -> None:
    with pytest.raises(UnsupportedRmfVersionError):
        load_schema("9.9.9")


# --- 1.0.0: files written by 1.1.3 ---------------------------------------------------


def test_v113_rmf_still_validates_and_matches_its_digest() -> None:
    document = json.loads(V113_RMF.read_text(encoding="utf-8"))
    assert document["rmf_schema_version"] == "1.0.0"
    jsonschema.validate(document, load_schema("1.0.0"))
    assert content_digest(document) == document["sha256_hash"]


def test_v113_rmf_is_not_valid_1_1_0() -> None:
    document = json.loads(V113_RMF.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**document, "rmf_schema_version": "1.1.0"}, load_schema("1.1.0"))


def test_1_0_0_digest_is_the_1_1_3_rule_even_without_the_blanked_keys() -> None:
    document = json.loads(V113_RMF.read_text(encoding="utf-8"))
    expected = sha256_hex(
        canonical_json({**document, "sha256_hash": "", "audit_entry_hash": "", "signed_by": ""})
    )
    assert content_digest(document) == expected
    trimmed = {k: v for k, v in document.items() if k not in ("audit_entry_hash", "signed_by")}
    assert content_digest(trimmed) == expected


# --- 1.1.0: new documents ------------------------------------------------------------


def test_new_documents_are_1_1_0_and_validate() -> None:
    document = rmf_document(_rmf())
    assert RMF_SCHEMA_VERSION == "1.1.0"
    assert document["rmf_schema_version"] == "1.1.0"
    jsonschema.validate(document, load_schema("1.1.0"))


def test_new_documents_carry_empty_provenance_arrays_and_no_retired_fields() -> None:
    document = rmf_document(_rmf())
    assert document["signoffs"] == []
    assert document["signatures"] == []
    assert document["public_keys"] == []
    assert "signed_by" not in document
    assert "audit_entry_hash" not in document


def test_a_fully_populated_document_validates() -> None:
    document = rmf_document(_full_rmf())
    jsonschema.validate(document, load_schema("1.1.0"))
    assert document["chain_proof"]["scope"] == "project"
    assert document["receipt"]["seq"] == 1


@pytest.mark.parametrize("field", ["signed_by", "audit_entry_hash"])
def test_1_1_0_rejects_the_retired_provenance_fields(field: str) -> None:
    document = rmf_document(_rmf())
    value = "x" if field == "signed_by" else "0" * 64
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**document, field: value}, load_schema("1.1.0"))


def test_register_block_keeps_the_names_and_test_requirements() -> None:
    document = rmf_document(_rmf())
    item = document["register"]["items"][0]
    assert item["accepted_by"] == "Jane Doe"
    assert item["mitigations"][0]["recorded_by"] == "Sam Lee"
    assert document["register"]["test_requirements"][0]["metric_type"] == "demographic_parity"


def test_register_block_is_the_register_as_the_model_serialises_it() -> None:
    rmf = _rmf()
    assert rmf_document(rmf)["register"] == rmf.register.model_dump(mode="json")


def test_chain_proof_entries_leave_out_unset_optional_fields() -> None:
    entries = rmf_document(_full_rmf())["chain_proof"]["entries"]
    assert "key_id" not in entries[0]
    assert "signature" not in entries[0]
    assert {"key_id", "signature"} <= set(entries[1])


def _provenance_objects(document: dict) -> dict[str, dict]:
    return {
        "signoff": document["signoffs"][0],
        "signature": document["signatures"][0],
        "public_key": document["public_keys"][0],
        "chain_proof": document["chain_proof"],
        "chain_proof_entry": document["chain_proof"]["entries"][0],
        "chain_proof_entry_actor": document["chain_proof"]["entries"][0]["actor"],
        "receipt": document["receipt"],
    }


@pytest.mark.parametrize(
    "target",
    [
        "signoff",
        "signature",
        "public_key",
        "chain_proof",
        "chain_proof_entry",
        "chain_proof_entry_actor",
        "receipt",
    ],
)
def test_each_provenance_object_refuses_an_extra_property(target: str) -> None:
    document = copy.deepcopy(rmf_document(_full_rmf()))
    jsonschema.validate(document, load_schema("1.1.0"))
    _provenance_objects(document)[target]["extra"] = "x"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, load_schema("1.1.0"))


@pytest.mark.parametrize("where", ["register", "item", "mitigation", "test_requirement"])
def test_register_objects_refuse_an_extra_property(where: str) -> None:
    document = copy.deepcopy(rmf_document(_rmf()))
    register = document["register"]
    target = {
        "register": register,
        "item": register["items"][0],
        "mitigation": register["items"][0]["mitigations"][0],
        "test_requirement": register["test_requirements"][0],
    }[where]
    target["extra"] = "x"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, load_schema("1.1.0"))


def test_a_signoff_without_its_signature_fails() -> None:
    document = copy.deepcopy(rmf_document(_full_rmf()))
    del document["signoffs"][0]["signature"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, load_schema("1.1.0"))


@pytest.mark.parametrize("drop", ["key_id", "signature"])
def test_a_chain_proof_entry_signed_by_halves_fails(drop: str) -> None:
    document = copy.deepcopy(rmf_document(_full_rmf()))
    del document["chain_proof"]["entries"][1][drop]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, load_schema("1.1.0"))


@pytest.mark.parametrize("drop", ["key_id", "public_key", "signature"])
def test_a_receipt_signed_by_halves_fails(drop: str) -> None:
    document = copy.deepcopy(rmf_document(_full_rmf()))
    del document["receipt"][drop]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, load_schema("1.1.0"))


def test_an_empty_chain_proof_fails() -> None:
    document = copy.deepcopy(rmf_document(_full_rmf()))
    document["chain_proof"]["entries"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(document, load_schema("1.1.0"))


# --- the content digest --------------------------------------------------------------


def test_digest_ignores_identity_time_and_provenance_but_covers_content() -> None:
    document = rmf_document(_full_rmf())
    base = content_digest(document)
    assert base == document["sha256_hash"]
    for key, value in (
        ("id", str(uuid4())),
        ("generated_at", "2030-01-01T00:00:00Z"),
        ("sha256_hash", "0" * 64),
        ("receipt", {"seq": 99}),
        ("chain_proof", {"scope": "project", "entries": []}),
        ("signatures", []),
        ("public_keys", []),
    ):
        assert content_digest({**document, key: value}) == base, key
    for key in ("receipt", "chain_proof", "signatures", "public_keys"):
        assert content_digest({k: v for k, v in document.items() if k != key}) == base, key

    changed = json.loads(json.dumps(document))
    changed["register"]["assessor_name"] = "Someone else"
    assert content_digest(changed) != base
    for key, value in (
        ("signoffs", []),
        ("test_requirements", [{"x": 1}]),
        ("cross_references", [{"x": 1}]),
        ("disclosure", "other"),
    ):
        assert content_digest({**document, key: value}) != base, key


def test_digest_reads_a_missing_signoffs_key_as_empty() -> None:
    document = rmf_document(_rmf())
    without = {k: v for k, v in document.items() if k != "signoffs"}
    assert content_digest(without) == content_digest(document)


def test_digest_is_the_canonical_json_of_the_content_fields() -> None:
    document = rmf_document(_rmf())
    kept = ("rmf_schema_version", "register", "test_requirements", "cross_references")
    source = {key: document[key] for key in (*kept, "disclosure", "signoffs")}
    assert content_digest(document) == sha256_hex(canonical_json(source))


def test_two_documents_of_one_register_state_share_a_digest() -> None:
    register = _register()
    first = RiskManagementFile(register=register, generated_at=NOW)
    second = RiskManagementFile(register=register, generated_at=NOW + timedelta(hours=1))
    assert first.id != second.id
    assert content_digest(rmf_document(first)) == content_digest(rmf_document(second))


@pytest.mark.parametrize("version", ["9.9.9", None, "1.1"])
def test_unknown_version_is_refused(version: str | None) -> None:
    with pytest.raises(UnsupportedRmfVersionError):
        content_digest({"rmf_schema_version": version})


# --- signing messages ----------------------------------------------------------------


def test_rmf_signing_message_is_the_prefix_and_the_hex_digest() -> None:
    assert rmf_signing_message("ab" * 32) == b"riskforge.rmf.v1\n" + b"ab" * 32


def test_signoff_signing_message_covers_every_field_but_the_signature() -> None:
    signoff = _signoff(_signer())
    body = signoff.model_dump(mode="json", exclude={"signature"})
    assert body["comment"] == ""  # a missing comment is signed as ""
    assert "key_id" in body
    assert signoff_signing_message(signoff) == b"riskforge.signoff.v1\n" + canonical_json(body)
    resigned = signoff.model_copy(update={"signature": "other"})
    assert signoff_signing_message(resigned) == signoff_signing_message(signoff)
    with_comment = signoff.model_copy(update={"comment": "ok"})
    assert signoff_signing_message(with_comment) != signoff_signing_message(signoff)


def test_signoff_refuses_an_unknown_field() -> None:
    data = _signoff(_signer()).model_dump(mode="json")
    with pytest.raises(ValueError):
        SignOff.model_validate({**data, "extra": "x"})


# --- reading an RMF file -------------------------------------------------------------


def test_read_rmf_file_returns_the_document(tmp_path: Path) -> None:
    path = tmp_path / "rmf.json"
    path.write_text(json.dumps(rmf_document(_rmf())), encoding="utf-8")
    assert read_rmf_file(path)["rmf_schema_version"] == "1.1.0"


@pytest.mark.parametrize(
    "text", ['{"rmf_schema_version": "1.1.0", "a": 1, "a": 2}', '{"x": NaN}', '{"x": 1e400}']
)
def test_read_rmf_file_refuses_duplicate_keys_and_non_finite_numbers(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / "rmf.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(StrictJsonError):
        read_rmf_file(path)


@pytest.mark.parametrize("content", [b"not json", b"\xff\xfe\x00", b"[1, 2]"])
def test_read_rmf_file_refuses_what_is_not_a_json_object(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "rmf.json"
    path.write_bytes(content)
    with pytest.raises(RmfFileError):
        read_rmf_file(path)


# --- TestRequirement moved -----------------------------------------------------------


def test_test_requirement_is_importable_from_every_old_path() -> None:
    from riskforge.models import TestRequirement as from_package
    from riskforge.models.requirements import TestRequirement
    from riskforge.models.rmf import TestRequirement as from_rmf

    assert from_package is TestRequirement
    assert from_rmf is TestRequirement


def test_register_test_requirements_default_empty_and_left_out_when_empty() -> None:
    system = AISystem(name="S", version="1", purpose="p", provider_name="P")
    register = RiskRegister(system=system, assessor_name="A", assessor_role="B")
    assert register.test_requirements == []
    assert "test_requirements" not in register.model_dump(mode="json")
