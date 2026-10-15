"""verify --file: digest, signatures, sign-offs, chain proof and receipt (ADR-04 section 6)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from rf_testkit import run_rf
from riskforge.integrity.canonical import document_fingerprint
from riskforge.integrity.chain import compute_entry_hash
from riskforge.integrity.rmf import content_digest, rmf_signing_message, signoff_signing_message
from riskforge.integrity.signing import Ed25519Signer
from riskforge.models.audit import AuditEntry
from riskforge.models.rmf import SignOff

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "credit-scoring"
V113_RMF = REPO / "tests" / "fixtures" / "v1_1_3_project" / "rmf.json"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DIGEST_ONLY = "only its content digest was checked"
REFUSED_1_0_0 = "RMF schema 1.0.0 cannot carry a signature"

Document = dict[str, Any]


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """One project exported three times: signed, signed again, and unsigned."""
    project = tmp_path_factory.mktemp("exported")
    config = yaml.safe_load((EXAMPLE / "config.yaml").read_text())
    init = run_rf(
        ["init", "-n", config["name"], "-s", str(config["version"]), "-p", config["purpose"]]
        + ["--provider", config["provider"], "-c", config["category"]]
        + ["--project-dir", str(project)]
    )
    assert init.returncode == 0, init.output
    sid = UUID_RE.search(init.output).group(0)
    assess = run_rf(
        ["assess", sid, "-a", "A. Assessor", "-r", "Risk Lead"]
        + ["--answers", str(EXAMPLE / "answers.yaml"), "--project-dir", str(project)]
    )
    assert assess.returncode == 0, assess.output
    keys = tmp_path_factory.mktemp("keys")
    key, other = keys / "k.pem", keys / "other.pem"
    for path in (key, other):
        assert run_rf(["keygen", "-o", str(path)]).returncode == 0
    files = {"first": ["--sign", str(key)], "second": ["--sign", str(key)], "unsigned": []}
    paths: dict[str, Path] = {"key": key, "other": other}
    for name, extra in files.items():
        out = project / f"{name}.json"
        result = run_rf(
            ["export", sid, "-o", str(out), "--force", *extra, "--project-dir", str(project)]
        )
        assert result.returncode == 0, result.output
        paths[name] = out
    return paths


def _verify(path: Path, *extra: str):  # noqa: ANN202
    return run_rf(["verify", "--file", str(path), *extra])


def _load(path: Path) -> Document:
    document: Document = json.loads(path.read_text())
    return document


def _write(document: Document, tmp_path: Path, name: str = "edited.json") -> Path:
    out = tmp_path / name
    out.write_text(json.dumps(document, indent=2))
    return out


def _signer(path: Path) -> Ed25519Signer:
    return Ed25519Signer.from_file(path)


def _redigest(document: Document, signer: Ed25519Signer | None = None) -> Document:
    """Recompute the digest, and re-sign the RMF signature with ``signer``, as a forger would."""
    document["sha256_hash"] = content_digest(document)
    if signer is not None:
        message = rmf_signing_message(document["sha256_hash"])
        for record in document["signatures"]:
            record["signature"] = signer.sign(message)
    return document


def _relink(entries: list[Document]) -> list[Document]:
    """Recompute every prev_hash and entry_hash, so the chain proof links check again."""
    prev = "0000000000"
    for raw in entries:
        raw["prev_hash"] = prev
        raw["entry_hash"] = ""
        raw["entry_hash"] = compute_entry_hash(AuditEntry.model_validate(raw))
        prev = raw["entry_hash"]
    return entries


def _system_id(document: Document) -> str:
    system_id: str = document["register"]["system"]["id"]
    return system_id


# --- untouched files ---------------------------------------------------------------


def test_signed_export_verifies_and_names_what_was_checked(exported) -> None:
    result = _verify(exported["second"])
    assert result.returncode == 0, result.output
    assert "RMF integrity verified" in result.output
    assert "not a trusted key check" not in result.output
    assert "Not checked" not in result.output
    assert "--trusted-key" in result.output  # the signer was not checked against a trusted key
    assert "Chain proof" in result.output
    assert "receipt" in result.output.lower()


def test_unsigned_export_verifies(exported) -> None:
    result = _verify(exported["unsigned"])
    assert result.returncode == 0, result.output
    assert "Not checked" not in result.output
    assert "not signed" in result.output


def test_v113_file_verifies_with_the_digest_only_note() -> None:
    result = _verify(V113_RMF)
    assert result.returncode == 0, result.output
    assert DIGEST_ONLY in result.output
    assert "1.0.0" in result.output


# --- edits that a forger did not cover ------------------------------------------------


def _edit_register(d: Document) -> None:
    d["register"]["items"][0]["likelihood"] = (
        1 if d["register"]["items"][0]["likelihood"] != 1 else 2
    )


def _edit_chain_proof(d: Document) -> None:
    d["chain_proof"]["entries"][0]["actor"]["identity"] = "someone-else"


def _edit_receipt(d: Document) -> None:
    d["receipt"]["issued_at"] = "2030-01-01T00:00:00Z"


@pytest.mark.parametrize(
    ("change", "finding"),
    [
        (_edit_register, "does not match its SHA-256 digest"),
        (_edit_chain_proof, "entry_hash mismatch"),
        (_edit_receipt, "embedded receipt: the signature does not verify"),
        (lambda d: d.update(audit_entry_hash="0" * 64), "audit_entry_hash"),
        (lambda d: d.update(signed_by="ciso@bank.example (forged)"), "signed_by"),
    ],
    ids=["register", "chain-proof", "receipt", "audit-entry-hash", "signed-by"],
)
def test_an_edited_file_fails(exported, tmp_path: Path, change, finding: str) -> None:
    document = _load(exported["second"])
    change(document)
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert finding in result.output
    assert "Traceback" not in result.output


def test_an_edited_rmf_signature_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    document["signatures"][0]["signature"] = _signer(exported["key"]).sign(b"something else")
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "RMF signature 1 by" in result.output
    assert "does not verify" in result.output


def test_a_register_edited_with_the_digest_recomputed_fails_the_chain_proof(
    exported, tmp_path: Path
) -> None:
    """The digest and the signature can be redone with the signer's key; the chain cannot."""
    document = _load(exported["second"])
    _edit_register(document)
    result = _verify(_write(_redigest(document, _signer(exported["key"])), tmp_path))
    assert result.returncode == 2, result.output
    assert "is not the state the chain proof records last" in result.output
    assert "embedded receipt" in result.output
    assert "SHA-256 digest" not in result.output


# --- the chain proof and the receipt ---------------------------------------------------


def test_an_entry_appended_after_the_receipt_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    entries = document["chain_proof"]["entries"]
    last = entries[-1]
    extra = {
        "seq": last["seq"] + 1,
        "event": "project.note",
        "timestamp": last["timestamp"],
        "actor": {"type": "human", "identity": "someone"},
        "system_id": "",
        "payload": {},
        "prev_hash": last["entry_hash"],
        "entry_hash": "",
    }
    extra["entry_hash"] = compute_entry_hash(AuditEntry.model_validate(extra))
    entries.append(extra)
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "but the last chain proof entry is seq" in result.output
    assert "entry_hash mismatch" not in result.output


def test_an_empty_chain_proof_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["unsigned"])
    document["chain_proof"]["entries"] = []
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "chain_proof/entries" in result.output


def test_a_chain_proof_with_no_fingerprint_for_the_system_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["unsigned"])
    for raw in document["chain_proof"]["entries"]:
        raw.pop("register_fingerprint", None)
    _relink(document["chain_proof"]["entries"])
    last = document["chain_proof"]["entries"][-1]
    document["receipt"].update(seq=last["seq"], entry_hash=last["entry_hash"])
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "records no register fingerprint for system" in result.output


def test_a_last_fingerprint_that_is_not_the_register_fails(exported, tmp_path: Path) -> None:
    """The chain proof is relinked and the receipt moved, so only the fingerprint is wrong."""
    document = _load(exported["unsigned"])
    entries = document["chain_proof"]["entries"]
    sid = _system_id(document)
    last_for_system = max(
        i for i, e in enumerate(entries) if e["system_id"] == sid and "register_fingerprint" in e
    )
    entries[last_for_system]["register_fingerprint"] = "d" * 64
    _relink(entries)
    last = entries[-1]
    document["receipt"].update(seq=last["seq"], entry_hash=last["entry_hash"])
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "is not the state the chain proof records last" in result.output


def test_an_entry_key_id_without_a_signature_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["unsigned"])
    document["chain_proof"]["entries"][0]["key_id"] = "ed25519:0123456789abcdef"
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "'signature' is a dependency of 'key_id'" in result.output


def test_an_entry_signature_without_a_key_id_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["unsigned"])
    document["chain_proof"]["entries"][0]["signature"] = "A" * 86 + "=="
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "'key_id' is a dependency of 'signature'" in result.output


def test_signed_chain_proof_entries_are_verified(exported, tmp_path: Path) -> None:
    """A signed entry must verify with its public_keys record, and an edited one fails."""
    signer = _signer(exported["other"])
    document = _load(exported["unsigned"])
    entries = document["chain_proof"]["entries"]
    entries[0]["key_id"] = signer.key_id
    _relink(entries)
    entries[0]["signature"] = signer.sign(
        b"riskforge.audit-entry.v1\n" + entries[0]["entry_hash"].encode()
    )
    last = entries[-1]
    document["receipt"].update(seq=last["seq"], entry_hash=last["entry_hash"])
    document["public_keys"] = [
        {"key_id": signer.key_id, "algorithm": "ed25519", "public_key": signer.public_key_b64}
    ]
    good = _verify(_write(document, tmp_path, "good.json"))
    assert good.returncode == 0, good.output

    entries[0]["signature"] = signer.sign(b"something else")
    bad = _verify(_write(document, tmp_path, "bad.json"))
    assert bad.returncode == 2, bad.output
    assert "Chain proof entry seq 0: the signature by" in bad.output

    document["public_keys"] = []
    missing = _verify(_write(document, tmp_path, "missing.json"))
    assert missing.returncode == 2, missing.output
    assert "has no record in public_keys" in missing.output


def test_a_receipt_for_another_system_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["unsigned"])
    document["receipt"]["system_id"] = "\x1b[31m[bold]other[/bold]"
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "is for system" in result.output
    assert "\x1b" not in result.output  # file text is shown as escapes, never sent raw
    assert "[bold]other[/bold]" in result.output


def test_a_receipt_with_a_null_fingerprint_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["unsigned"])
    document["receipt"]["register_fingerprint"] = None
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "embedded receipt's register_fingerprint" in result.output


@pytest.mark.parametrize(
    ("change", "finding"),
    [
        (
            lambda d: d["chain_proof"]["entries"][0].update(timestamp="not a time"),
            "not a valid audit entry",
        ),
        (lambda d: d["receipt"].update(issued_at="not a time"), "not a valid receipt"),
    ],
    ids=["chain-proof-entry", "receipt"],
)
def test_a_value_the_schema_lets_through_but_a_model_refuses_fails(
    exported, tmp_path: Path, change, finding: str
) -> None:
    """The schema does not check date-time formats; reading the block as a model does."""
    document = _load(exported["unsigned"])
    change(document)
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert finding in result.output
    assert "Traceback" not in result.output


# --- public keys -------------------------------------------------------------------------


def test_duplicate_public_key_ids_fail(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    document["public_keys"].append(dict(document["public_keys"][0]))
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "holds 2 records for key id" in result.output


def test_a_key_id_with_no_record_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    document["public_keys"] = []
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "RMF signature 1 names key id" in result.output
    assert "has no record in public_keys" in result.output


def test_a_record_whose_key_id_is_not_its_key_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    document["public_keys"][0]["public_key"] = _signer(exported["other"]).public_key_b64
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "its key_id is not the key id of its public_key" in result.output


def test_a_wrong_algorithm_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    document["public_keys"][0]["algorithm"] = "rsa"
    document["signatures"][0]["algorithm"] = "rsa"
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "public_keys/0/algorithm" in result.output
    assert "signatures/0/algorithm" in result.output
    assert "were not checked, because it does not validate against its schema" in result.output


def test_a_receipt_public_key_that_differs_from_its_record_fails(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    document["receipt"]["public_key"] = _signer(exported["other"]).public_key_b64
    result = _verify(_write(document, tmp_path))
    assert result.returncode == 2, result.output
    assert "public_key differs from the public_keys record for its key_id" in result.output


# --- strict reading ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "finding"),
    [
        (
            lambda t: t.replace('"assessor_name":', '"assessor_name": "x",\n"assessor_name":', 1),
            "duplicate key 'assessor_name'",
        ),
        (lambda t: t.replace('"seq": 0', '"seq": 0, "seq": 0', 1), "duplicate key 'seq'"),
        (lambda t: re.sub(r'"likelihood": \d', '"likelihood": NaN', t, count=1), "NaN"),
        (lambda t: re.sub(r'"likelihood": \d', '"likelihood": 1e400', t, count=1), "1e400"),
        (lambda t: t.replace('"seq": 0', '"seq": -Infinity', 1), "-Infinity"),
    ],
    ids=["register-duplicate", "chain-proof-duplicate", "nan", "overflow", "infinity"],
)
def test_strict_reading_refuses_what_riskforge_never_writes(
    exported, tmp_path: Path, mutate, finding: str
) -> None:
    out = tmp_path / "rmf.json"
    out.write_text(mutate(exported["second"].read_text()))
    result = _verify(out)
    assert result.returncode == 2, result.output
    assert finding in result.output
    assert "Traceback" not in result.output


# --- sign-offs -------------------------------------------------------------------------------


def _with_signoff(
    exported: dict[str, Path],
    tmp_path: Path,
    *,
    signoff_key: str = "key",
    fingerprint: str | None = None,
    tamper: bool = False,
) -> Path:
    """The signed export with one sign-off, digest and RMF signature redone by its key."""
    document = _load(exported["second"])
    signer = _signer(exported[signoff_key])
    signoff = SignOff(
        approver="approver@client.example",
        decision="approved",
        version_number=1,
        register_fingerprint=fingerprint or document_fingerprint(document["register"]),
        totp_verified_at=datetime(2026, 10, 1, tzinfo=UTC),
        signed_at=datetime(2026, 10, 1, 0, 1, tzinfo=UTC),
        key_id=signer.key_id,
        signature="",
    )
    signoff.signature = signer.sign(signoff_signing_message(signoff))
    raw = signoff.model_dump(mode="json")
    if tamper:
        raw["decision"] = "rejected"
    document["signoffs"] = [raw]
    if signer.key_id not in {record["key_id"] for record in document["public_keys"]}:
        document["public_keys"].append(
            {"key_id": signer.key_id, "algorithm": "ed25519", "public_key": signer.public_key_b64}
        )
    _redigest(document, _signer(exported["key"]))
    name = f"signoff-{signoff_key}-{tamper}-{(fingerprint or 'good')[:4]}.json"
    return _write(document, tmp_path, name)


def test_a_valid_signoff_verifies(exported, tmp_path: Path) -> None:
    result = _verify(_with_signoff(exported, tmp_path))
    assert result.returncode == 0, result.output
    assert "Sign-off 1" in result.output
    assert "approved" in result.output


def test_an_edited_signoff_fails(exported, tmp_path: Path) -> None:
    result = _verify(_with_signoff(exported, tmp_path, tamper=True))
    assert result.returncode == 2, result.output
    assert "Sign-off 1: the signature does not verify" in result.output


def test_a_signoff_that_is_not_a_valid_signoff_fails(exported, tmp_path: Path) -> None:
    document = _load(_with_signoff(exported, tmp_path))
    document["signoffs"][0]["totp_verified_at"] = "not a time"
    result = _verify(_write(_redigest(document, _signer(exported["key"])), tmp_path))
    assert result.returncode == 2, result.output
    assert "Sign-off 1 is not a valid sign-off" in result.output


def test_a_signoff_for_another_register_state_fails(exported, tmp_path: Path) -> None:
    result = _verify(_with_signoff(exported, tmp_path, fingerprint="d" * 64))
    assert result.returncode == 2, result.output
    assert "Sign-off 1 is for register fingerprint" in result.output


def test_a_signoff_by_an_untrusted_key_fails_with_trusted_key(exported, tmp_path: Path) -> None:
    path = _with_signoff(exported, tmp_path, signoff_key="other")
    assert _verify(path).returncode == 0
    result = _verify(path, "--trusted-key", f"{exported['key']}.pub")
    assert result.returncode == 2, result.output
    assert "Sign-off 1 is signed by" in result.output
    assert "not a trusted key" in result.output


# --- --trusted-key --------------------------------------------------------------------------


def test_trusted_key_passes_when_it_signed(exported) -> None:
    result = _verify(exported["second"], "--trusted-key", f"{exported['key']}.pub")
    assert result.returncode == 0, result.output
    assert "a trusted key" in result.output


def test_trusted_key_fails_when_another_key_signed(exported) -> None:
    result = _verify(exported["second"], "--trusted-key", f"{exported['other']}.pub")
    assert result.returncode == 2, result.output
    assert "RMF signature 1 is by" in result.output
    assert "embedded receipt is signed by" in result.output


def test_trusted_key_requires_an_rmf_signature(exported) -> None:
    result = _verify(exported["unsigned"], "--trusted-key", f"{exported['key']}.pub")
    assert result.returncode == 2, result.output
    assert "carries no RMF signature" in result.output
    assert "embedded receipt is not signed" in result.output


def test_trusted_key_requires_a_signed_receipt(exported, tmp_path: Path) -> None:
    document = _load(exported["second"])
    for name in ("key_id", "public_key", "signature"):
        document["receipt"].pop(name)
    path = _write(document, tmp_path)
    assert _verify(path).returncode == 0
    result = _verify(path, "--trusted-key", f"{exported['key']}.pub")
    assert result.returncode == 2, result.output
    assert "embedded receipt is not signed" in result.output


def test_a_trusted_key_file_that_is_not_a_public_key_exits_3(exported) -> None:
    result = _verify(exported["second"], "--trusted-key", str(exported["second"]))
    assert result.returncode == 3, result.output


# --- 1.0.0 files ------------------------------------------------------------------------------


def _downgraded(exported: dict[str, Path], tmp_path: Path) -> Path:
    """A signed 1.1.0 file rewritten as 1.0.0: provenance dropped, the 1.0.0 digest redone."""
    document = _load(exported["second"])
    for name in ("signoffs", "signatures", "public_keys", "chain_proof", "receipt"):
        document.pop(name)
    document["register"].pop("test_requirements", None)
    for item in document["register"]["items"]:
        item.pop("accepted_by", None)
        for mitigation in item.get("mitigations", []):
            mitigation.pop("recorded_by", None)
    document["register"]["items"][0]["title"] = "Edited after the export"
    document["rmf_schema_version"] = "1.0.0"
    document["sha256_hash"] = ""
    document["sha256_hash"] = content_digest(document)
    return _write(document, tmp_path, "downgraded.json")


def test_a_downgraded_file_passes_plain_verify_with_the_digest_only_note(
    exported, tmp_path: Path
) -> None:
    result = _verify(_downgraded(exported, tmp_path))
    assert result.returncode == 0, result.output
    assert DIGEST_ONLY in result.output


def test_a_downgraded_file_fails_with_trusted_key(exported, tmp_path: Path) -> None:
    result = _verify(_downgraded(exported, tmp_path), "--trusted-key", f"{exported['key']}.pub")
    assert result.returncode == 2, result.output
    assert REFUSED_1_0_0 in result.output


def test_a_downgraded_file_fails_with_receipt(exported, tmp_path: Path) -> None:
    result = _verify(_downgraded(exported, tmp_path), "--receipt", str(exported["first"]))
    assert result.returncode == 2, result.output
    assert REFUSED_1_0_0 in result.output


def test_the_v113_file_fails_with_trusted_key(exported) -> None:
    result = _verify(V113_RMF, "--trusted-key", f"{exported['key']}.pub")
    assert result.returncode == 2, result.output
    assert REFUSED_1_0_0 in result.output


# --- --receipt with --file -------------------------------------------------------------------


def test_an_older_receipt_holds_in_a_newer_file(exported) -> None:
    result = _verify(exported["second"], "--receipt", str(exported["first"]))
    assert result.returncode == 0, result.output
    assert "the chain proof holds its entry at seq" in result.output


def test_a_newer_receipt_fails_against_an_older_file(exported) -> None:
    result = _verify(exported["first"], "--receipt", str(exported["unsigned"]))
    assert result.returncode == 2, result.output
    assert "has no entry at seq" in result.output


def test_a_receipt_file_with_the_wrong_fingerprint_fails(exported, tmp_path: Path) -> None:
    receipt = _load(exported["first"])["receipt"]
    for name in ("key_id", "public_key", "signature"):
        receipt.pop(name)
    receipt["register_fingerprint"] = "d" * 64
    path = _write(receipt, tmp_path, "receipt.json")
    result = _verify(exported["second"], "--receipt", str(path))
    assert result.returncode == 2, result.output
    assert "its register fingerprint for system" in result.output


def test_a_receipt_file_checked_against_trusted_keys(exported, tmp_path: Path) -> None:
    trusted = ("--trusted-key", f"{exported['key']}.pub")
    assert (
        _verify(exported["second"], "--receipt", str(exported["first"]), *trusted).returncode == 0
    )
    receipt = _load(exported["first"])["receipt"]
    for name in ("key_id", "public_key", "signature"):
        receipt.pop(name)
    path = _write(receipt, tmp_path, "unsigned-receipt.json")
    result = _verify(exported["second"], "--receipt", str(path), *trusted)
    assert result.returncode == 2, result.output
    assert "is not signed, and a trusted key is required" in result.output


def test_a_receipt_file_with_a_duplicate_key_fails(exported, tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_text(exported["first"].read_text().replace('"seq":', '"seq": 0, "seq":', 1))
    result = _verify(exported["second"], "--receipt", str(path))
    assert result.returncode == 2, result.output


def test_a_receipt_file_that_is_not_json_exits_3(exported, tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    path.write_text("not json")
    result = _verify(exported["second"], "--receipt", str(path))
    assert result.returncode == 3, result.output


# --- --strict ------------------------------------------------------------------------------------


def test_strict_with_file_is_still_a_usage_error(exported) -> None:
    """File mode has no warnings for --strict to turn into failures (see the verify help)."""
    result = _verify(exported["second"], "--strict")
    assert result.returncode == 3, result.output
    assert "--strict cannot be combined with --file" in result.output


def test_help_has_no_em_dash() -> None:
    result = run_rf(["verify", "--help"])
    assert result.returncode == 0
    assert "—" not in result.stdout
    assert "cannot be combined with --file yet" not in result.stdout
