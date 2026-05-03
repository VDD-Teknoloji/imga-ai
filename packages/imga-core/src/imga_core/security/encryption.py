"""Fernet symmetric encryption for tenant-scoped secrets.

Sprint 8.3.6 / Alt-Faz 8.3.6.1.C. The master key lives outside git on
the host (``/etc/imga-secrets/master.key``, ``root:root``, mode 0600)
and is mounted into the api container as a Docker secret at
``/run/secrets/imga/master.key`` (mode 0400). The path is read from
``IMGA_MASTER_KEY_PATH`` so tests + tooling can swap to a repo-local
``infra/imga/test/secrets/master.key`` without code changes.

Loss of the key invalidates every ``tenant_llm_credentials.encrypted_value``
row — recovery requires re-entering the API keys. There is no
key-derivation / rotation path in 8.3.6; that lands when the vault
arrives in Sprint 9.0+.

Public surface:

  * ``encrypt(plaintext: str) -> bytes`` — UTF-8 → Fernet-token bytes.
    Empty plaintext is rejected (``ValueError``) so a None-coalescing
    upstream bug can't silently store an unencrypted ciphertext.
  * ``decrypt(ciphertext: bytes) -> str`` — inverse. Invalid token /
    key mismatch raises ``EncryptionError`` (no plaintext leakage in
    the message).
  * ``reset_fernet_cache()`` — test hook; clears the lru_cache so
    a fixture that swaps ``IMGA_MASTER_KEY_PATH`` mid-process picks
    up the new key on the next call.

The Fernet instance is cached via ``lru_cache`` so the disk read +
key parse happens once per process. That cache is the only piece of
state in this module; everything else is pure.
"""

from __future__ import annotations

import os
import pathlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(Exception):
    """Raised when the master key is unreachable or a ciphertext fails
    authentication. Never includes the plaintext or the key in its
    message."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Lazy-load the Fernet instance from the configured master key
    path. Cached for the lifetime of the process (tests use
    ``reset_fernet_cache()`` to invalidate)."""
    key_path = os.getenv("IMGA_MASTER_KEY_PATH", "/run/secrets/imga/master.key")
    p = pathlib.Path(key_path)
    if not p.exists():
        raise EncryptionError(f"Master key not found at {key_path}")
    key = p.read_bytes().strip()
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise EncryptionError(f"Master key at {key_path} is malformed") from exc


def reset_fernet_cache() -> None:
    """Clear the cached Fernet instance. Call from tests after
    swapping ``IMGA_MASTER_KEY_PATH`` so the next ``encrypt`` /
    ``decrypt`` re-reads the file. No-op outside tests."""
    _get_fernet.cache_clear()


def encrypt(plaintext: str) -> bytes:
    """Encrypt a non-empty UTF-8 string. Returns the raw Fernet token
    bytes (URL-safe base64), suitable for storage in a Postgres
    ``BYTEA`` column.

    Raises:
        ValueError: ``plaintext`` is empty. The contract is "never
            silently encrypt nothing"; an upstream None coalescing
            bug should fail loud here, not produce a token that
            decrypts to ``""``.
        EncryptionError: master key file is missing or malformed.
    """
    if not plaintext:
        raise ValueError("Cannot encrypt empty plaintext")
    return _get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    """Inverse of ``encrypt``. Returns the original UTF-8 string.

    Raises:
        EncryptionError: ciphertext is corrupt, truncated, signed
            with a different key, or the master key file is missing.
            The original ``InvalidToken`` is preserved as ``__cause__``
            for log traceability without surfacing it to callers.
    """
    try:
        return _get_fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError(
            "Failed to decrypt — key mismatch or tampered ciphertext"
        ) from exc
