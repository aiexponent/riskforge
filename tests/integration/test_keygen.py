"""riskforge keygen writes a private key only its owner can read, and never overwrites."""

from __future__ import annotations

import base64
import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from rf_testkit import run_rf
from riskforge.integrity.signing import Ed25519Signer, load_public_key_b64


def test_keygen_writes_a_private_key_only_its_owner_can_read(tmp_path: Path) -> None:
    key = tmp_path / "signing.pem"
    public = tmp_path / "signing.pem.pub"
    result = run_rf(["keygen", "--output", str(key)])
    assert result.returncode == 0, result.output
    if os.name == "posix":
        assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert key.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")  # gitleaks:allow
    assert public.read_bytes().startswith(b"-----BEGIN PUBLIC KEY-----")
    signer = Ed25519Signer.from_file(key)
    assert load_public_key_b64(public) == signer.public_key_b64
    assert signer.key_id in result.output
    assert signer.public_key_b64 in result.output


def test_keygen_never_prints_the_private_key(tmp_path: Path) -> None:
    key = tmp_path / "signing.pem"
    result = run_rf(["keygen", "--output", str(key)])
    assert result.returncode == 0, result.output
    private_key = serialization.load_pem_private_key(key.read_bytes(), password=None)
    raw_private = private_key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    assert "PRIVATE KEY" not in result.output
    assert base64.b64encode(raw_private).decode() not in result.output
    assert raw_private.hex() not in result.output
    pem_body = "".join(key.read_text().splitlines()[1:-1])
    assert pem_body not in result.output


@pytest.mark.parametrize("existing", ["signing.pem", "signing.pem.pub"])
def test_keygen_never_overwrites(tmp_path: Path, existing: str) -> None:
    (tmp_path / existing).write_bytes(b"keep me\n")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = run_rf(["keygen", "--output", str(tmp_path / "signing.pem")])
    assert result.returncode == 3, result.output
    assert "already exists" in result.output
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def _listing(directory: Path) -> dict[str, object]:
    return {
        p.name: os.readlink(p) if p.is_symlink() else p.read_bytes() for p in directory.iterdir()
    }


@pytest.mark.parametrize("dangling", [True, False])
@pytest.mark.parametrize("existing", ["signing.pem", "signing.pem.pub"])
def test_keygen_refuses_a_symlink(tmp_path: Path, existing: str, dangling: bool) -> None:
    keys = tmp_path / "keys"
    keys.mkdir()
    target = tmp_path / "target"
    if not dangling:
        target.write_bytes(b"keep me\n")
    try:
        (keys / existing).symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symlinks here")
    before = _listing(keys)
    result = run_rf(["keygen", "--output", str(keys / "signing.pem")])
    assert result.returncode == 3, result.output
    assert "already exists" in result.output
    assert _listing(keys) == before
    if dangling:
        assert not target.exists()
    else:
        assert target.read_bytes() == b"keep me\n"


def test_keygen_twice_keeps_the_first_key(tmp_path: Path) -> None:
    key = tmp_path / "signing.pem"
    assert run_rf(["keygen", "--output", str(key)]).returncode == 0
    before = (key.read_bytes(), (tmp_path / "signing.pem.pub").read_bytes())
    result = run_rf(["keygen", "--output", str(key)])
    assert result.returncode == 3, result.output
    assert (key.read_bytes(), (tmp_path / "signing.pem.pub").read_bytes()) == before


def test_keygen_exits_3_when_the_directory_is_missing(tmp_path: Path) -> None:
    result = run_rf(["keygen", "--output", str(tmp_path / "nope" / "signing.pem")])
    assert result.returncode == 3, result.output
    assert not (tmp_path / "nope").exists()


def test_keygen_requires_output() -> None:
    result = run_rf(["keygen"])
    assert result.returncode == 3, result.output
    assert "--output" in result.output
