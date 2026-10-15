"""riskforge receipt and verify --receipt / --trusted-key, end to end (ADR-04 section 5)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from rf_testkit import run_rf
from riskforge.integrity.chain import compute_entry_hash, entry_to_dict
from riskforge.models.audit import AuditEntry

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

posix_only = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")


def _rf(project: Path, *args: str):
    return run_rf([*args, "--project-dir", str(project)])


def _seed(project: Path) -> str:
    project.mkdir()
    result = run_rf(
        [
            "init",
            "-n",
            "S",
            "-s",
            "1",
            "-p",
            "credit scoring for loans",
            "--provider",
            "P",
            "-c",
            "essential_services",
            "--project-dir",
            str(project),
        ]
    )
    assert result.returncode == 0, result.output
    sid = UUID_RE.search(result.output).group(0)
    answers = project.parent / "answers.yaml"
    answers.write_text(
        "add_patterns: false\nanswers:\n"
        "  PR-001: { applies: yes, likelihood: 3, severity: 4 }\n"
        "  TR-001: { applies: yes, likelihood: 2, severity: 3 }\n"
    )
    assessed = _rf(project, "assess", sid, "-a", "A", "-r", "B", "--answers", str(answers))
    assert assessed.returncode == 0, assessed.output
    return sid


def _riskforge(project: Path) -> Path:
    return project / ".riskforge"


def _log_lines(project: Path) -> list[str]:
    return (_riskforge(project) / "audit.jsonl").read_text().splitlines(keepends=True)


def _accept_first_risk(project: Path, sid: str) -> None:
    register = yaml.safe_load((_riskforge(project) / "systems" / sid / "register.yaml").read_text())
    risk_id = register["items"][0]["id"]
    result = _rf(project, "risk", "accept", sid, risk_id, "-r", "within appetite", "--by", "QA")
    assert result.returncode == 0, result.output


def _keygen(path: Path) -> Path:
    result = run_rf(["keygen", "--output", str(path)])
    assert result.returncode == 0, result.output
    return path


def _receipt(project: Path, sid: str, path: Path, *extra: str) -> None:
    result = _rf(project, "receipt", sid, "--output", str(path), *extra)
    assert result.returncode == 0, result.output


def test_receipt_records_the_chain_head_and_verifies(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    data = json.loads(path.read_text())
    last = json.loads(_log_lines(project)[-1])
    assert data["receipt_version"] == "1"
    assert data["system_id"] == sid
    assert (data["seq"], data["entry_hash"]) == (last["seq"], last["entry_hash"])
    assert data["register_fingerprint"] == last["register_fingerprint"]
    assert data["issued_at"]
    assert not {"key_id", "public_key", "signature"} & set(data)

    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 0, result.output
    assert f"seq {last['seq']}" in result.output


@posix_only
def test_receipt_file_is_written_with_mode_600(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_receipt_without_output_prints_json(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    result = _rf(project, "receipt", sid)
    assert result.returncode == 0, result.output
    data = json.loads(result.stdout)
    assert data["system_id"] == sid
    assert data["seq"] == json.loads(_log_lines(project)[-1])["seq"]


def test_receipt_never_overwrites_a_file(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    path.write_text("{}")
    result = _rf(project, "receipt", sid, "--output", str(path))
    assert result.returncode == 3, result.output
    assert "already exists" in result.output
    assert path.read_text() == "{}"
    missing_dir = _rf(project, "receipt", sid, "--output", str(tmp_path / "nope" / "r.json"))
    assert missing_dir.returncode == 3, missing_dir.output


def test_receipt_for_an_unknown_system_exits_3(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _seed(project)
    result = _rf(project, "receipt", "00000000-0000-0000-0000-000000000000")
    assert result.returncode == 3, result.output


def test_receipt_refuses_a_project_that_fails_its_integrity_check(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    register = _riskforge(project) / "systems" / sid / "register.yaml"
    register.write_text(register.read_text().replace("A", "Z", 1))
    path = tmp_path / "receipt.json"
    result = _rf(project, "receipt", sid, "--output", str(path))
    assert result.returncode == 2, result.output
    assert not path.exists()


def test_receipt_catches_a_cut_log_with_the_head_file_rewritten(tmp_path: Path) -> None:
    """ADR-03's documented limit: plain verify passes, verify --receipt does not."""
    project = tmp_path / "p"
    sid = _seed(project)
    systems_copy = tmp_path / "systems-before"
    shutil.copytree(_riskforge(project) / "systems", systems_copy)
    kept = _log_lines(project)
    _accept_first_risk(project, sid)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    assert len(_log_lines(project)) > len(kept)

    # The attacker cuts the last entries off, puts the files back as they were, and
    # rewrites the head file to match the new end of the log.
    (_riskforge(project) / "audit.jsonl").write_text("".join(kept))
    shutil.rmtree(_riskforge(project) / "systems")
    shutil.copytree(systems_copy, _riskforge(project) / "systems")
    last = json.loads(kept[-1])
    (_riskforge(project) / "audit.head.json").write_text(
        json.dumps({"seq": last["seq"], "entry_hash": last["entry_hash"]})
    )

    plain = _rf(project, "verify")
    assert plain.returncode == 0, plain.output
    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 2, result.output
    assert "truncated or replaced" in result.output


def test_receipt_catches_a_rewritten_entry_with_the_head_file_rewritten(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    lines = _log_lines(project)
    entry = AuditEntry.model_validate_json(lines[-1])
    entry = entry.model_copy(update={"timestamp": entry.timestamp - timedelta(days=1)})
    entry.entry_hash = compute_entry_hash(entry)
    lines[-1] = json.dumps(entry_to_dict(entry)) + "\n"
    (_riskforge(project) / "audit.jsonl").write_text("".join(lines))
    (_riskforge(project) / "audit.head.json").write_text(
        json.dumps({"seq": entry.seq, "entry_hash": entry.entry_hash})
    )

    plain = _rf(project, "verify")
    assert plain.returncode == 0, plain.output
    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 2, result.output
    assert "rewritten" in result.output


def test_every_receipt_given_is_checked(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    good = tmp_path / "good.json"
    _receipt(project, sid, good)
    bad = tmp_path / "bad.json"
    data = json.loads(good.read_text())
    bad.write_text(json.dumps({**data, "seq": data["seq"] + 50}))
    result = _rf(project, "verify", "--receipt", str(good), "--receipt", str(bad))
    assert result.returncode == 2, result.output
    assert "bad.json" in result.output and "truncated or replaced" in result.output


def test_signed_receipt_with_trusted_keys(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    key = _keygen(tmp_path / "k.pem")
    other = _keygen(tmp_path / "other.pem")
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path, "--sign", str(key))
    data = json.loads(path.read_text())
    assert data["key_id"].startswith("ed25519:") and data["public_key"] and data["signature"]

    trusted = _rf(project, "verify", "--receipt", str(path), "--trusted-key", f"{key}.pub")
    assert trusted.returncode == 0, trusted.output
    either = _rf(
        project,
        "verify",
        "--receipt",
        str(path),
        "--trusted-key",
        f"{other}.pub",
        "--trusted-key",
        f"{key}.pub",
    )
    assert either.returncode == 0, either.output
    untrusted = _rf(project, "verify", "--receipt", str(path), "--trusted-key", f"{other}.pub")
    assert untrusted.returncode == 2, untrusted.output
    assert "not a trusted key" in untrusted.output


def test_unsigned_receipt_fails_with_a_trusted_key(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    key = _keygen(tmp_path / "k.pem")
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    result = _rf(project, "verify", "--receipt", str(path), "--trusted-key", f"{key}.pub")
    assert result.returncode == 2, result.output
    assert "not signed" in result.output


def test_altered_signed_receipt_fails(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    key = _keygen(tmp_path / "k.pem")
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path, "--sign", str(key))
    data = json.loads(path.read_text())
    data["register_fingerprint"] = None
    path.write_text(json.dumps(data))
    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 2, result.output
    assert "signature does not verify" in result.output


@posix_only
def test_receipt_refuses_a_key_others_can_read(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    key = _keygen(tmp_path / "k.pem")
    key.chmod(0o644)
    path = tmp_path / "receipt.json"
    result = _rf(project, "receipt", sid, "--output", str(path), "--sign", str(key))
    assert result.returncode == 3, result.output
    assert not path.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda text: text.replace('"seq":', '"seq": 0, "seq":', 1),
        lambda text: re.sub(r'"seq": \d+', '"seq": NaN', text, count=1),
    ],
)
def test_receipt_file_with_a_duplicate_key_or_nan_exits_2(tmp_path: Path, mutate) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    path.write_text(mutate(path.read_text()))
    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 2, result.output


def test_receipt_file_that_is_not_json_exits_3(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _seed(project)
    path = tmp_path / "receipt.json"
    path.write_text("not json")
    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 3, result.output


def test_receipt_and_trusted_key_cannot_be_combined_with_file(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    key = _keygen(tmp_path / "k.pem")
    rmf = tmp_path / "rmf.json"
    rmf.write_text('{"sha256_hash": "x"}')
    for extra in (["--receipt", str(path)], ["--trusted-key", f"{key}.pub"]):
        result = _rf(project, "verify", "--file", str(rmf), *extra)
        assert result.returncode == 3, result.output


def test_verify_checks_signed_audit_entries_with_trusted_keys(tmp_path: Path) -> None:
    """The free CLI does not sign entries, so the project is written through the engine."""
    from riskforge.engine.audit import AuditEngine
    from riskforge.engine.system import SystemEngine
    from riskforge.integrity.signing import Ed25519Signer
    from riskforge.models.audit import AuditActor
    from riskforge.models.system import AISystem
    from riskforge.storage.filesystem import FileStore

    key = _keygen(tmp_path / "k.pem")
    other = _keygen(tmp_path / "other.pem")
    project = tmp_path / "p"

    async def build() -> None:
        store = FileStore(project)
        await store.init_project("p", {})
        audit = AuditEngine(
            store, AuditActor(type="api", identity="server"), signer=Ed25519Signer.from_file(key)
        )
        system = AISystem(name="S", version="1", purpose="credit scoring", provider_name="P")
        await SystemEngine(store, audit).create(system)

    asyncio.run(build())
    unchecked = _rf(project, "verify")
    assert unchecked.returncode == 0, unchecked.output
    assert "not checked" in unchecked.output
    assert _rf(project, "verify", "--strict").returncode == 2
    trusted = _rf(project, "verify", "--trusted-key", f"{key}.pub")
    assert trusted.returncode == 0, trusted.output
    assert "not checked" not in trusted.output
    untrusted = _rf(project, "verify", "--trusted-key", f"{other}.pub")
    assert untrusted.returncode == 2, untrusted.output
    assert "not a trusted key" in untrusted.output


def test_receipt_fingerprint_that_differs_from_the_chain_exits_2(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    data = json.loads(path.read_text())
    for edited in ({**data, "register_fingerprint": "0" * 64}, {**data, "system_id": "other"}):
        changed = tmp_path / f"edited-{len(edited['system_id'])}.json"
        changed.write_text(json.dumps(edited))
        result = _rf(project, "verify", "--receipt", str(changed))
        assert result.returncode == 2, result.output
        assert "register fingerprint" in result.output


def test_receipt_file_with_a_seq_too_long_for_python_exits_2(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    path.write_text(re.sub(r'"seq": \d+', '"seq": ' + "9" * 5000, path.read_text(), count=1))
    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 2, result.output
    assert "Traceback" not in result.output
    assert "too long" in result.output


def test_control_characters_from_a_receipt_file_never_reach_the_terminal(tmp_path: Path) -> None:
    project = tmp_path / "p"
    sid = _seed(project)
    path = tmp_path / "receipt.json"
    _receipt(project, sid, path)
    data = json.loads(path.read_text())
    data["\x1b]0;owned\x07\x1b[2J‮x\x9b\x7f"] = "x"
    path.write_text(json.dumps(data))  # json.dumps writes the characters as \u escapes
    result = _rf(project, "verify", "--receipt", str(path))
    assert result.returncode == 2, result.output
    for char in ("\x1b", "\x07", "‮", "\x9b", "\x7f"):
        assert char not in result.output, repr(char)
    assert "\\x1b]0;owned" in result.output


def test_trusted_key_names_the_unsigned_entries_and_strict_fails_on_them(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _seed(project)
    key = _keygen(tmp_path / "k.pem")
    count = len(_log_lines(project))
    assert _rf(project, "verify", "--strict").returncode == 0
    plain = _rf(project, "verify")
    assert plain.returncode == 0 and "not signed" not in plain.output, plain.output
    trusted = _rf(project, "verify", "--trusted-key", f"{key}.pub")
    assert trusted.returncode == 0, trusted.output
    assert f"{count} audit entries are not signed" in trusted.output
    strict = _rf(project, "verify", "--strict", "--trusted-key", f"{key}.pub")
    assert strict.returncode == 2, strict.output
    assert f"{count} audit entries are not signed" in strict.output
