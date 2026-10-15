"""Ed25519 keys and signatures.

Key files are PEM: the private key as unencrypted PKCS8, the public key as
SubjectPublicKeyInfo. Inside RiskForge documents a public key is the base64 of its
32 raw bytes, and ``key_id`` is ``"ed25519:"`` plus the first 16 hex characters of the
SHA-256 of those bytes. The key id is a label for lookup only: trust always compares
the full public key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

KEY_ID_PREFIX = "ed25519:"


class KeyFileError(ValueError):
    """A key file is missing, unreadable, or not an Ed25519 key."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _raw_public(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _read_key_file(path: Path, kind: str) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise KeyFileError(f"{kind} file not found: {path}") from exc
    except OSError as exc:
        raise KeyFileError(
            f"Cannot read {kind.lower()} file {path}: {exc.strerror or exc}"
        ) from exc


PUBLIC_KEY_BYTES = 32


def decode_public_key(public_key_b64: object) -> bytes:
    """The 32 raw bytes of a base64 Ed25519 public key, decoded strictly.

    Raises ``ValueError`` for a value that is not a string, not valid base64, or not
    32 bytes long.
    """
    if not isinstance(public_key_b64, str):
        raise ValueError("the public key is not a string")
    try:
        raw = base64.b64decode(public_key_b64, validate=True)
    except binascii.Error as exc:
        raise ValueError("the public key is not valid base64") from exc
    if len(raw) != PUBLIC_KEY_BYTES:
        raise ValueError(f"the public key is {len(raw)} bytes, not {PUBLIC_KEY_BYTES}")
    return raw


def key_id_for(public_key_b64: str) -> str:
    """The key id of a base64 raw public key."""
    raw = base64.b64decode(public_key_b64, validate=True)
    return KEY_ID_PREFIX + hashlib.sha256(raw).hexdigest()[:16]


def _new_key_pair() -> tuple[bytes, bytes, str]:
    """A new key pair as (private PEM, public PEM, base64 raw public key)."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private_pem, public_pem, _b64(_raw_public(public_key))


def generate_key_pair_pem() -> tuple[bytes, bytes]:
    """A new key pair as (PKCS8 private PEM, SubjectPublicKeyInfo public PEM)."""
    private_pem, public_pem, _public_b64 = _new_key_pair()
    return private_pem, public_pem


def public_key_path(private_path: Path) -> Path:
    """Where the public key of *private_path* goes: the same name plus ``.pub``."""
    return private_path.with_name(private_path.name + ".pub")


def write_key_pair(private_path: Path) -> str:
    """Create a new key pair at *private_path* and its ``.pub`` file; return the public key.

    On POSIX systems the private key file is created with mode 600; on Windows it takes
    the directory's ACLs. Neither file is ever overwritten: ``KeyFileError`` when either
    exists or the directory is missing, and nothing is written then. If writing fails or
    is interrupted, the files this call created are removed.
    """
    public_path = public_key_path(private_path)
    if not private_path.parent.is_dir():
        raise KeyFileError(f"Directory does not exist: {private_path.parent}")
    for path in (private_path, public_path):
        if path.exists() or path.is_symlink():
            raise KeyFileError(
                f"{path} already exists. RiskForge never overwrites a key; choose another --output."
            )
    private_pem, public_pem, public_b64 = _new_key_pair()
    created: list[Path] = []
    try:
        for path, data, mode in (
            (private_path, private_pem, 0o600),
            (public_path, public_pem, 0o644),
        ):
            # O_EXCL: fail instead of following a symlink or replacing a file created meanwhile.
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), mode
            )
            created.append(path)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
    except BaseException as exc:
        # Also on KeyboardInterrupt: never leave a partial key behind. Only files in
        # `created` are removed, so a file someone else made in the meantime stays.
        for path in created:
            path.unlink(missing_ok=True)
        if isinstance(exc, FileExistsError):
            raise KeyFileError(
                f"{exc.filename} already exists. RiskForge never overwrites a key; "
                "choose another --output."
            ) from exc
        if isinstance(exc, OSError):
            raise KeyFileError(f"Cannot write key file: {exc.strerror or exc}") from exc
        raise
    return public_b64


class Ed25519Signer:
    """Signs messages with one private key and names it by ``key_id``."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key
        self.public_key_b64 = _b64(_raw_public(private_key.public_key()))
        self.key_id = key_id_for(self.public_key_b64)

    @classmethod
    def from_file(cls, path: Path) -> Ed25519Signer:
        """Load an unencrypted PEM private key; ``KeyFileError`` for anything else."""
        return cls.from_pem(_read_key_file(path, "Key"), path)

    @classmethod
    def from_pem(cls, pem: bytes, source: Path) -> Ed25519Signer:
        """Load an unencrypted PEM private key read from *source* (named in errors)."""
        try:
            key = serialization.load_pem_private_key(pem, password=None)
        except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
            raise KeyFileError(f"{source} is not an unencrypted PEM private key.") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise KeyFileError(f"{source} holds a {type(key).__name__}, not an Ed25519 key.")
        return cls(key)

    def sign(self, message: bytes) -> str:
        """The base64 Ed25519 signature of *message*."""
        return _b64(self._private_key.sign(message))


def load_public_key_b64(path: Path) -> str:
    """Read a PEM public key file (as `riskforge keygen` writes) as base64 raw bytes."""
    pem = _read_key_file(path, "Public key")
    try:
        key = serialization.load_pem_public_key(pem)
    except (ValueError, UnsupportedAlgorithm) as exc:
        raise KeyFileError(f"{path} is not a PEM public key.") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise KeyFileError(f"{path} holds a {type(key).__name__}, not an Ed25519 key.")
    return _b64(_raw_public(key))


def verify_signature(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    """True when ``signature_b64`` is a valid Ed25519 signature of ``message``.

    False for anything else, including a key or signature that is not a string (a null
    or a number in a parsed document) or is not valid base64.
    """
    if not isinstance(public_key_b64, str) or not isinstance(signature_b64, str):
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True)
        )
        public_key.verify(base64.b64decode(signature_b64, validate=True), message)
    except (InvalidSignature, ValueError, binascii.Error):
        return False
    return True
