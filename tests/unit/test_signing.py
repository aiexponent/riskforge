"""Ed25519 helpers: keys, ids, signatures, and the CLI key loaders."""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

import pytest
import typer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from riskforge.cli.project import load_signer, load_trusted_keys
from riskforge.integrity import signing
from riskforge.integrity.signing import (
    Ed25519Signer,
    KeyFileError,
    generate_key_pair_pem,
    key_id_for,
    load_public_key_b64,
    public_key_path,
    verify_signature,
    write_key_pair,
)

posix_only = pytest.mark.skipif(os.name != "posix", reason="file modes are POSIX only")


def _key_files(tmp_path: Path, name: str = "k.pem") -> tuple[Path, Path]:
    private_pem, public_pem = generate_key_pair_pem()
    private = tmp_path / name
    public = tmp_path / f"{name}.pub"
    private.write_bytes(private_pem)
    public.write_bytes(public_pem)
    private.chmod(0o600)
    return private, public


def _flip_one_byte_b64(value: str, index: int = 0) -> str:
    raw = bytearray(base64.b64decode(value))
    raw[index] ^= 0x01
    return base64.b64encode(bytes(raw)).decode("ascii")


def test_key_pair_formats(tmp_path: Path) -> None:
    private_pem, public_pem = generate_key_pair_pem()
    assert private_pem.startswith(b"-----BEGIN PRIVATE KEY-----")  # gitleaks:allow
    assert public_pem.startswith(b"-----BEGIN PUBLIC KEY-----")  # SubjectPublicKeyInfo
    assert serialization.load_pem_private_key(private_pem, password=None) is not None


def test_key_id_is_sha256_of_the_raw_key(tmp_path: Path) -> None:
    private, _public = _key_files(tmp_path)
    signer = Ed25519Signer.from_file(private)
    raw = base64.b64decode(signer.public_key_b64, validate=True)
    assert len(raw) == 32
    assert signer.key_id == "ed25519:" + hashlib.sha256(raw).hexdigest()[:16]
    assert key_id_for(signer.public_key_b64) == signer.key_id


def test_signature_verifies_and_detects_changes(tmp_path: Path) -> None:
    private, public = _key_files(tmp_path)
    signer = Ed25519Signer.from_file(private)
    assert signer.public_key_b64 == load_public_key_b64(public)
    signature = signer.sign(b"message")
    assert verify_signature(signer.public_key_b64, b"message", signature)
    assert not verify_signature(signer.public_key_b64, b"messagE", signature)
    for index in (0, 31, 63):
        assert not verify_signature(
            signer.public_key_b64, b"message", _flip_one_byte_b64(signature, index)
        )
    assert not verify_signature(signer.public_key_b64, b"message", "not base64!")
    assert not verify_signature("not base64!", b"message", signature)
    assert not verify_signature(base64.b64encode(b"short").decode(), b"message", signature)


@pytest.mark.parametrize("length", [0, 32, 63, 65, 128])
def test_wrong_length_signature_does_not_verify(tmp_path: Path, length: int) -> None:
    private, _public = _key_files(tmp_path)
    signer = Ed25519Signer.from_file(private)
    signature = base64.b64decode(signer.sign(b"message"))
    wrong = (signature * 3)[:length]
    assert not verify_signature(
        signer.public_key_b64, b"message", base64.b64encode(wrong).decode("ascii")
    )


@pytest.mark.parametrize("bad", [None, 0, 7, 1.5, b"bytes", ["list"]])
def test_verify_signature_is_false_for_non_string_input(tmp_path: Path, bad: object) -> None:
    # A receipt parsed from JSON can carry null or a number where a string belongs.
    private, _public = _key_files(tmp_path)
    signer = Ed25519Signer.from_file(private)
    signature = signer.sign(b"message")
    assert not verify_signature(bad, b"message", signature)  # type: ignore[arg-type]
    assert not verify_signature(signer.public_key_b64, b"message", bad)  # type: ignore[arg-type]


def test_verify_signature_is_false_for_non_ascii_base64(tmp_path: Path) -> None:
    private, _public = _key_files(tmp_path)
    signer = Ed25519Signer.from_file(private)
    assert not verify_signature(signer.public_key_b64, b"message", "\u00e9" * 88)
    assert not verify_signature("\u00e9" * 44, b"message", signer.sign(b"message"))


def test_other_key_does_not_verify(tmp_path: Path) -> None:
    private, _public = _key_files(tmp_path)
    other_private, _other_public = _key_files(tmp_path, "other.pem")
    signature = Ed25519Signer.from_file(private).sign(b"m")
    other = Ed25519Signer.from_file(other_private)
    assert not verify_signature(other.public_key_b64, b"m", signature)


def _ec_key_files(tmp_path: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = tmp_path / "ec.pem"
    public = tmp_path / "ec.pem.pub"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    private.chmod(0o600)
    return private, public


def test_bad_key_files_raise_key_file_error(tmp_path: Path) -> None:
    _private, public = _key_files(tmp_path)
    ec_private, ec_public = _ec_key_files(tmp_path)
    with pytest.raises(KeyFileError, match="not found"):
        Ed25519Signer.from_file(tmp_path / "missing.pem")
    with pytest.raises(KeyFileError):
        Ed25519Signer.from_file(public)
    with pytest.raises(KeyFileError, match="not an Ed25519 key"):
        Ed25519Signer.from_file(ec_private)
    with pytest.raises(KeyFileError, match="not an Ed25519 key"):
        load_public_key_b64(ec_public)
    with pytest.raises(KeyFileError):
        Ed25519Signer.from_file(tmp_path)
    (tmp_path / "junk.pem").write_text("junk")
    with pytest.raises(KeyFileError):
        load_public_key_b64(tmp_path / "junk.pem")
    with pytest.raises(KeyFileError, match="not found"):
        load_public_key_b64(tmp_path / "missing.pem.pub")


def _exit_code(call) -> int:
    with pytest.raises(typer.Exit) as excinfo:
        call()
    return excinfo.value.exit_code


def test_load_signer_accepts_an_owner_only_key(tmp_path: Path) -> None:
    private, public = _key_files(tmp_path)
    assert load_signer(private).public_key_b64 == load_public_key_b64(public)


def test_load_signer_exits_3_for_a_missing_or_wrong_key(tmp_path: Path) -> None:
    _private, public = _key_files(tmp_path)
    public.chmod(0o600)
    ec_private, _ec_public = _ec_key_files(tmp_path)
    assert _exit_code(lambda: load_signer(tmp_path / "missing.pem")) == 3
    assert _exit_code(lambda: load_signer(public)) == 3
    assert _exit_code(lambda: load_signer(ec_private)) == 3


@posix_only
@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644, 0o660])
def test_load_signer_exits_3_when_others_can_read_the_key(tmp_path: Path, mode: int) -> None:
    private, _public = _key_files(tmp_path)
    private.chmod(mode)
    assert _exit_code(lambda: load_signer(private)) == 3


@posix_only
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads any file")
def test_load_signer_exits_3_for_an_unreadable_key(tmp_path: Path) -> None:
    private, _public = _key_files(tmp_path)
    private.chmod(0o000)
    try:
        assert _exit_code(lambda: load_signer(private)) == 3
    finally:
        private.chmod(0o600)


def test_load_trusted_keys(tmp_path: Path) -> None:
    _a, a_pub = _key_files(tmp_path, "a.pem")
    _b, b_pub = _key_files(tmp_path, "b.pem")
    assert load_trusted_keys([a_pub, b_pub]) == [
        load_public_key_b64(a_pub),
        load_public_key_b64(b_pub),
    ]
    assert load_trusted_keys([]) == []
    assert _exit_code(lambda: load_trusted_keys([a_pub, tmp_path / "missing.pub"])) == 3


def test_write_key_pair_returns_the_public_key_without_reading_it_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_reads(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("write_key_pair read a key file back from disk")

    monkeypatch.setattr(signing, "_read_key_file", no_reads)
    monkeypatch.setattr(signing, "load_public_key_b64", no_reads)
    key = tmp_path / "k.pem"
    public_b64 = write_key_pair(key)
    monkeypatch.undo()
    assert public_b64 == load_public_key_b64(public_key_path(key))
    assert public_b64 == Ed25519Signer.from_file(key).public_key_b64


def test_write_key_pair_removes_its_private_key_when_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fdopen = os.fdopen

    def interrupted_fdopen(fd: int, *args: object, **kwargs: object) -> object:
        real_fdopen(fd, *args, **kwargs).close()
        raise KeyboardInterrupt

    monkeypatch.setattr(signing.os, "fdopen", interrupted_fdopen)
    with pytest.raises(KeyboardInterrupt):
        write_key_pair(tmp_path / "k.pem")
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


def test_write_key_pair_keeps_a_pub_file_that_appears_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = tmp_path / "k.pem"
    public = public_key_path(key)
    real_open = os.open

    def racing_open(path: object, *args: object, **kwargs: object) -> int:
        if Path(str(path)) == public:
            public.write_bytes(b"someone else's file\n")
        return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(signing.os, "open", racing_open)
    with pytest.raises(KeyFileError, match="already exists"):
        write_key_pair(key)
    monkeypatch.undo()
    assert not key.exists()
    assert public.read_bytes() == b"someone else's file\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["k.pem.pub"]


@posix_only
def test_load_signer_exits_3_for_a_symlinked_key(tmp_path: Path) -> None:
    private, _public = _key_files(tmp_path)
    link = tmp_path / "link.pem"
    link.symlink_to(private)
    assert _exit_code(lambda: load_signer(link)) == 3


def test_load_signer_exits_3_for_a_directory(tmp_path: Path) -> None:
    (tmp_path / "dir.pem").mkdir()
    assert _exit_code(lambda: load_signer(tmp_path / "dir.pem")) == 3


@posix_only
def test_load_signer_exits_3_for_a_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo.pem"
    os.mkfifo(fifo, 0o600)
    assert _exit_code(lambda: load_signer(fifo)) == 3
