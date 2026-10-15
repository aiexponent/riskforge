"""Export (ADR-04 section 7): one digest across formats, atomic write, entry after write.

Each export embeds a chain proof and a receipt, stages a `register.checkpoint` when the
stored register is not the current model's serialisation, and records `rmf.exported`
only once the file exists. A failure before the commit leaves no file and no entry.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import time
from pathlib import Path

import pytest
from rf_testkit import pdf_text, run_rf
from riskforge.engine.audit import AuditEngine
from riskforge.engine.export import TEMP_PREFIX, ExportEngine, SchemaViolationError
from riskforge.integrity.canonical import document_fingerprint
from riskforge.integrity.receipts import receipt_signing_message
from riskforge.integrity.rmf import rmf_signing_message
from riskforge.integrity.signing import verify_signature
from riskforge.models.audit import AuditActor
from riskforge.models.receipt import Receipt
from riskforge.plugins.registry import PluginRegistry
from riskforge.storage.filesystem import FileStore


def _project(tmp_path: Path, name: str = "Export Test System") -> tuple[Path, str]:
    """A 2.0 project with one classified system and a small register."""
    from riskforge.engine.risk import RiskEngine
    from riskforge.engine.system import SystemEngine
    from riskforge.models.risk import Likelihood, RiskDimension, RiskItem, Severity

    project = tmp_path / "project"
    project.mkdir()
    init = run_rf(
        [
            "init",
            "--name",
            name,
            "--sys-version",
            "1.0",
            "--purpose",
            "Ranks job applicants for interview.",
            "--provider",
            "AI Exponent LLC",
            "--category",
            "employment",
            "--project-dir",
            str(project),
        ]
    )
    assert init.returncode == 0, init.output
    sid = next(
        line.split(":", 1)[-1].strip() for line in init.output.splitlines() if "System ID:" in line
    )

    async def seed() -> None:
        store = FileStore(project)
        audit = AuditEngine(store, AuditActor(type="ci", identity="export-test"))
        await SystemEngine(store, audit).classify(sid, None)
        engine = RiskEngine(store, audit)
        await engine.create_register(sid, "Test Assessor", "QA Engineer")
        for dimension in (RiskDimension.privacy, RiskDimension.discrimination):
            await engine.add_risk(
                sid,
                RiskItem(
                    dimension=dimension,
                    title=f"Export test risk: {dimension.value}",
                    description="Seeded by the export tests.",
                    source="manual",
                    likelihood=Likelihood.possible,
                    severity=Severity.moderate,
                    residual_likelihood=Likelihood.unlikely,
                    residual_severity=Severity.minor,
                ),
            )

    asyncio.run(seed())
    return project, sid


def _log(project: Path) -> bytes:
    return (project / ".riskforge" / "audit.jsonl").read_bytes()


def _events(project: Path) -> list[dict]:
    return [json.loads(line) for line in _log(project).decode("utf-8").splitlines()]


def _stored_files(project: Path, sid: str) -> dict[str, bytes | None]:
    """Every file an export could change, as bytes (None when absent)."""
    root = project / ".riskforge"
    paths = [
        root / "audit.jsonl",
        root / "audit.head.json",
        root / "systems" / sid / "register.yaml",
        root / "systems" / sid / "mitigations.yaml",
    ]
    return {str(p): (p.read_bytes() if p.exists() else None) for p in paths}


def _errors(output: str) -> list[str]:
    """The output lines that are not integrity warnings (a 1.1.3 project prints some)."""
    return [line for line in output.strip().splitlines() if not line.startswith("!")]


def _export(project: Path, sid: str, out: Path, *extra: str):
    return run_rf(["export", sid, "-o", str(out), "--force", *extra, "--project-dir", str(project)])


def _engine(project: Path) -> ExportEngine:
    store = FileStore(project)
    registry = PluginRegistry()
    registry.load_all()
    return ExportEngine(registry, AuditEngine(store, AuditActor(type="human", identity="t")), store)


def test_json_pdf_and_markdown_share_one_digest(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    for fmt, name in (("json", "rmf.json"), ("pdf", "rmf.pdf"), ("markdown", "rmf.md")):
        result = _export(project, sid, tmp_path / name, "-f", fmt)
        assert result.returncode == 0, result.output
    digest = json.loads((tmp_path / "rmf.json").read_text())["sha256_hash"]
    assert digest in (tmp_path / "rmf.md").read_text()
    assert digest in "".join(pdf_text(tmp_path / "rmf.pdf").split())
    payloads = [e["payload"] for e in _events(project) if e["event"] == "rmf.exported"]
    assert [p["sha256"] for p in payloads] == [digest] * 3
    assert [p["format"] for p in payloads] == ["json", "pdf", "markdown"]


def test_entry_is_recorded_after_the_file_with_its_bytes_digest(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    out = tmp_path / "rmf.json"
    result = _export(project, sid, out)
    assert result.returncode == 0, result.output
    data = out.read_bytes()
    assert data.endswith(b"}\n")
    last = _events(project)[-1]
    assert last["event"] == "rmf.exported"
    document = json.loads(data)
    assert set(last["payload"]) == {"export_id", "format", "sha256", "file_sha256"}
    assert last["payload"]["file_sha256"] == hashlib.sha256(data).hexdigest()
    assert last["payload"]["sha256"] == document["sha256_hash"]
    assert last["payload"]["export_id"] == document["id"]
    # The export's own entry is never in its file: the chain proof ends just before it.
    proof = document["chain_proof"]["entries"]
    assert proof[-1]["seq"] == last["seq"] - 1
    assert proof[-1]["entry_hash"] == last["prev_hash"]
    if os.name == "posix":
        assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_rmf_exported_is_recorded_only_once_the_file_exists(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    out = tmp_path / "rmf.json"
    engine = _engine(project)
    seen: list[tuple[str, bool]] = []
    record = engine._audit.record

    async def watching(event: str, system_id: str, payload: dict):
        seen.append((event, out.exists()))
        return await record(event, system_id, payload)

    engine._audit.record = watching  # type: ignore[method-assign]
    result = asyncio.run(engine.export(sid, "json", out, force=True))
    assert seen == [("rmf.exported", True)]
    assert result.file_sha256 == hashlib.sha256(out.read_bytes()).hexdigest()
    assert result.entry.event == "rmf.exported"


def test_every_export_carries_a_chain_proof_and_a_receipt_for_its_last_entry(
    tmp_path: Path,
) -> None:
    project, sid = _project(tmp_path)
    out = tmp_path / "rmf.json"
    assert _export(project, sid, out).returncode == 0
    document = json.loads(out.read_text())
    proof = document["chain_proof"]
    assert proof["scope"] == "project"
    stored = _events(project)[:-1]  # everything but this export's rmf.exported
    assert proof["entries"] == stored
    receipt = document["receipt"]
    assert (receipt["seq"], receipt["entry_hash"]) == (
        proof["entries"][-1]["seq"],
        proof["entries"][-1]["entry_hash"],
    )
    assert receipt["system_id"] == sid
    assert receipt["register_fingerprint"] == document_fingerprint(document["register"])
    assert "signature" not in receipt
    assert document["signatures"] == [] and document["public_keys"] == []


def test_two_exports_of_one_register_share_the_digest_and_need_no_checkpoint(
    tmp_path: Path,
) -> None:
    project, sid = _project(tmp_path)
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    assert _export(project, sid, first).returncode == 0
    assert _export(project, sid, second).returncode == 0
    a, b = json.loads(first.read_text()), json.loads(second.read_text())
    assert a["sha256_hash"] == b["sha256_hash"]
    assert a["id"] != b["id"]
    assert len(b["chain_proof"]["entries"]) == len(a["chain_proof"]["entries"]) + 1
    assert "register.checkpoint" not in [e["event"] for e in _events(project)]


def test_v113_project_exports_with_a_checkpoint(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    out = root / "new.json"
    result = _export(root, sid, out)
    assert result.returncode == 0, result.output
    events = _events(root)
    assert [e["event"] for e in events[-2:]] == ["register.checkpoint", "rmf.exported"]
    checkpoint = events[-2]
    assert set(checkpoint["payload"]) == {"riskforge_version"}
    document = json.loads(out.read_text())
    proof = document["chain_proof"]["entries"]
    fingerprint = document_fingerprint(document["register"])
    assert proof[-1]["event"] == "register.checkpoint"
    assert proof[-1]["register_fingerprint"] == fingerprint
    assert document["receipt"]["register_fingerprint"] == fingerprint
    # The committed checkpoint is the exact entry the file's chain proof ends with.
    lines = _log(root).decode("utf-8").splitlines()
    assert json.dumps(proof[-1], separators=(",", ":")) == lines[-2]
    assert run_rf(["verify", "--project-dir", str(root)]).returncode == 0


def test_missing_output_directory_leaves_no_file_and_no_checkpoint(
    v113_project: tuple[Path, str],
) -> None:
    root, sid = v113_project
    before = _stored_files(root, sid)
    result = _export(root, sid, root / "missing" / "dir" / "rmf.json")
    assert result.returncode == 3, result.output
    assert "does not exist" in result.output
    assert len(_errors(result.output)) == 1, result.output
    assert not (root / "missing").exists()
    assert _stored_files(root, sid) == before


@pytest.mark.skipif(
    os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions and a non-root user",
)
def test_unwritable_output_directory_exits_3_with_one_line(
    v113_project: tuple[Path, str], tmp_path: Path
) -> None:
    root, sid = v113_project
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    before = _stored_files(root, sid)
    try:
        result = _export(root, sid, locked / "rmf.json")
    finally:
        locked.chmod(0o700)
    assert result.returncode == 3, result.output
    assert len(_errors(result.output)) == 1, result.output
    assert list(locked.iterdir()) == []
    assert _stored_files(root, sid) == before


def test_failed_render_leaves_no_file_and_no_checkpoint(v113_project: tuple[Path, str]) -> None:
    root, sid = v113_project
    engine = _engine(root)

    class Broken:
        def render(self, rmf):
            raise RuntimeError("renderer crashed")

    engine._registry._exporters["broken"] = Broken
    before = _stored_files(root, sid)
    out = root / "rmf.broken"
    with pytest.raises(RuntimeError, match="renderer crashed"):
        asyncio.run(engine.export(sid, "broken", out, force=True))
    assert not out.exists()
    assert not [p for p in root.iterdir() if p.name.startswith(TEMP_PREFIX)]
    assert _stored_files(root, sid) == before


def test_schema_violation_leaves_no_file_and_no_checkpoint(
    v113_project: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import riskforge.engine.export as export_module

    root, sid = v113_project
    real = export_module.load_schema

    def strict_schema(version: str) -> dict:
        schema = real(version)
        schema["properties"]["disclosure"] = {"type": "string", "maxLength": 1}
        return schema

    monkeypatch.setattr(export_module, "load_schema", strict_schema)
    before = _stored_files(root, sid)
    out = root / "violating.json"
    with pytest.raises(SchemaViolationError):
        asyncio.run(_engine(root).export(sid, "json", out, force=True))
    assert not out.exists()
    assert _stored_files(root, sid) == before


def _project_id(project: Path) -> str:
    import yaml

    return yaml.safe_load((project / "riskforge.yaml").read_text(encoding="utf-8"))["project_id"]


def _hour_old(path: Path) -> None:
    hour_ago = time.time() - 3600
    os.utime(path, (hour_ago, hour_ago), follow_symlinks=False)


def test_a_stale_temporary_file_is_removed_by_the_next_export(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    target = tmp_path / "out"
    target.mkdir()
    stale = target / f"{TEMP_PREFIX}{_project_id(project)}-interrupted.tmp"
    stale.write_bytes(b'{"receipt": "for an entry never committed"}')
    hour_ago = time.time() - 3600
    os.utime(stale, (hour_ago, hour_ago))
    unrelated = target / ".notes.tmp"
    unrelated.write_text("keep me")
    os.utime(unrelated, (hour_ago, hour_ago))
    assert _export(project, sid, target / "rmf.json").returncode == 0
    assert not stale.exists()
    assert unrelated.exists()
    assert sorted(p.name for p in target.iterdir()) == [".notes.tmp", "rmf.json"]


def test_signed_export_embeds_the_signature_and_key(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    key = tmp_path / "k.pem"
    assert run_rf(["keygen", "-o", str(key)]).returncode == 0
    out = tmp_path / "rmf.json"
    result = _export(project, sid, out, "--sign", str(key))
    assert result.returncode == 0, result.output
    document = json.loads(out.read_text())
    [signature] = document["signatures"]
    [key_record] = document["public_keys"]
    assert signature["key_id"] == key_record["key_id"]
    assert signature["algorithm"] == key_record["algorithm"] == "ed25519"
    assert verify_signature(
        key_record["public_key"],
        rmf_signing_message(document["sha256_hash"]),
        signature["signature"],
    )
    receipt = document["receipt"]
    assert receipt["key_id"] == key_record["key_id"]
    assert receipt["public_key"] == key_record["public_key"]
    assert verify_signature(
        receipt["public_key"],
        receipt_signing_message(Receipt.model_validate(receipt)),
        receipt["signature"],
    )
    assert not (tmp_path / "rmf.json.asc").exists()
    assert key_record["key_id"] in result.output


def test_a_gpg_key_id_is_refused_with_no_file_and_no_entry(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    before = _stored_files(project, sid)
    out = tmp_path / "rmf.json"
    result = _export(project, sid, out, "--sign", "nobody@example.invalid")
    assert result.returncode == 3, result.output
    assert "riskforge keygen" in result.output
    assert not out.exists()
    assert not (tmp_path / "rmf.json.asc").exists()
    assert _stored_files(project, sid) == before


def test_failing_gates_stop_an_unforced_export(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    before = _stored_files(project, sid)
    out = tmp_path / "rmf.json"
    result = run_rf(["export", sid, "-o", str(out), "--project-dir", str(project)])
    assert result.returncode == 1, result.output
    assert "riskforge validate" in result.output
    assert not out.exists()
    assert _stored_files(project, sid) == before


def test_a_tampered_project_exits_2_and_writes_nothing(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    register = project / ".riskforge" / "systems" / sid / "register.yaml"
    register.write_text(register.read_text().replace("Test Assessor", "Someone Else"))
    out = tmp_path / "rmf.json"
    result = _export(project, sid, out)
    assert result.returncode == 2, result.output
    assert not out.exists()


def _tree(project: Path) -> dict[str, bytes]:
    """Every file under the project, as bytes, except the two opening the project creates."""
    return {
        str(p.relative_to(project)): p.read_bytes()
        for p in sorted(project.rglob("*"))
        if p.is_file() and not p.is_symlink() and p.name not in {"audit.lock", ".nodelete"}
    }


@pytest.mark.parametrize(
    "inside",
    [
        ".riskforge/audit.jsonl",
        ".riskforge/audit.head.json",
        ".riskforge/systems/{sid}/register.yaml",
        "riskforge.yaml",
    ],
)
def test_an_output_path_inside_the_project_data_is_refused(
    v113_project: tuple[Path, str], inside: str
) -> None:
    root, sid = v113_project
    before = _tree(root)
    result = _export(root, sid, root / inside.format(sid=sid))
    assert result.returncode == 3, result.output
    assert len(_errors(result.output)) == 1, result.output
    assert _tree(root) == before


@pytest.mark.skipif(os.name != "posix", reason="needs symlinks")
def test_an_output_path_through_a_symlink_into_the_project_data_is_refused(
    v113_project: tuple[Path, str], tmp_path: Path
) -> None:
    root, sid = v113_project
    link = tmp_path / "elsewhere"
    link.symlink_to(root / ".riskforge", target_is_directory=True)
    before = _tree(root)
    result = _export(root, sid, link / "audit.jsonl")
    assert result.returncode == 3, result.output
    assert len(_errors(result.output)) == 1, result.output
    assert _tree(root) == before


def test_an_existing_directory_as_output_is_refused_before_anything_is_staged(
    v113_project: tuple[Path, str], tmp_path: Path
) -> None:
    root, sid = v113_project
    before = _tree(root)
    result = _export(root, sid, tmp_path)
    assert result.returncode == 3, result.output
    assert len(_errors(result.output)) == 1, result.output
    assert _tree(root) == before


def test_stale_cleanup_leaves_another_projects_temporary_file_alone(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    target = tmp_path / "out"
    target.mkdir()
    other = target / f"{TEMP_PREFIX}8b1009b4-ffd2-40fb-adc1-4716c9da17b5-k3j2h1g0.tmp"
    other.write_bytes(b"another project's export in progress")
    _hour_old(other)
    assert _export(project, sid, target / "rmf.json").returncode == 0
    assert other.read_bytes() == b"another project's export in progress"


@pytest.mark.skipif(os.name != "posix", reason="needs symlinks")
def test_stale_cleanup_leaves_a_symlinked_temporary_file_alone(tmp_path: Path) -> None:
    project, sid = _project(tmp_path)
    target = tmp_path / "out"
    target.mkdir()
    victim = tmp_path / "keep.txt"
    victim.write_text("keep me")
    _hour_old(victim)
    link = target / f"{TEMP_PREFIX}{_project_id(project)}-linkedxx.tmp"
    link.symlink_to(victim)
    _hour_old(link)
    assert _export(project, sid, target / "rmf.json").returncode == 0
    assert link.is_symlink()
    assert victim.read_text() == "keep me"


def test_an_unremovable_stale_temporary_file_does_not_block_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, sid = _project(tmp_path)
    target = tmp_path / "out"
    target.mkdir()
    stuck = target / f"{TEMP_PREFIX}{_project_id(project)}-stuckxxx.tmp"
    stuck.write_bytes(b"cannot be removed")
    _hour_old(stuck)
    real_unlink = os.unlink

    def unlink(path, *args, **kwargs):
        if os.fspath(path) == str(stuck):
            raise PermissionError(1, "Operation not permitted", str(path))
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink)
    out = target / "rmf.json"
    result = asyncio.run(_engine(project).export(sid, "json", out, force=True))
    assert result.path == out and out.exists()
    assert stuck.exists()


def test_a_failed_rename_after_the_checkpoint_is_an_export_target_error(
    v113_project: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    from riskforge.engine.export import ExportTargetError

    root, sid = v113_project
    out = root / "never-written.json"
    real_replace = os.replace

    def replace(src, dst, *args, **kwargs):
        if os.fspath(dst) == str(out):
            raise OSError(errno.EXDEV, "Invalid cross-device link", str(dst))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    exported_before = [e["event"] for e in _events(root)].count("rmf.exported")
    with pytest.raises(
        ExportTargetError, match=r"register.checkpoint \(seq \d+\) was committed"
    ) as caught:
        asyncio.run(_engine(root).export(sid, "json", out, force=True))
    assert "No file was written" in str(caught.value)
    assert not out.exists()
    assert not [p for p in root.iterdir() if p.name.startswith(TEMP_PREFIX)]
    events = [e["event"] for e in _events(root)]
    assert events[-1] == "register.checkpoint"
    assert events.count("rmf.exported") == exported_before


def test_a_failed_directory_flush_after_the_rename_is_an_export_target_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    import riskforge.engine.export as export_module
    from riskforge.engine.export import ExportTargetError

    project, sid = _project(tmp_path)
    out = tmp_path / "rmf.json"

    def fsync_dir(directory: Path) -> None:
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(export_module, "_fsync_dir", fsync_dir)
    before = _log(project)
    with pytest.raises(ExportTargetError, match="could not be flushed"):
        asyncio.run(_engine(project).export(sid, "json", out, force=True))
    assert _log(project) == before
