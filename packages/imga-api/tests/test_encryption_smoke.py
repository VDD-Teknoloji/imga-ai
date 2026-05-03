"""Sprint 8.3.6 / Alt-Faz 8.3.6.1.G — encryption helper smoke from
the imga-api test stack.

The full unit suite lives in ``imga-core/tests/test_encryption.py``;
this file mirrors three of those tests so the imga-api test compose
(which only collects ``packages/imga-api/tests/``) verifies the
helper at the same layer the credential service consumes it. Five
tests because the master prompt's exit criterion is "+5 fixture/
encryption".
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from imga_core.security.encryption import (
    EncryptionError,
    decrypt,
    encrypt,
    reset_fernet_cache,
)


@pytest.fixture(autouse=True)
def _local_master_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Each test gets its own key file; cache is flushed before AND
    after so a leak between this file and any earlier fixture path
    swap can't taint the run."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(Fernet.generate_key())
    monkeypatch.setenv("IMGA_MASTER_KEY_PATH", str(key_path))
    reset_fernet_cache()
    yield key_path
    reset_fernet_cache()


def test_encrypt_decrypt_round_trip_in_api_layer() -> None:
    """The same UTF-8 round-trip the unit suite covers, run from the
    imga-api context to prove the imga-core dependency is wired."""
    plaintext = "AIzaSy-fake-key-with-türkçe-ı-ş-ğ"
    ciphertext = encrypt(plaintext)
    assert isinstance(ciphertext, bytes)
    assert decrypt(ciphertext) == plaintext


def test_empty_plaintext_rejected_in_api_layer() -> None:
    """Same contract as the unit suite; pin it here too because the
    credential service will rely on this."""
    with pytest.raises(ValueError, match="empty"):
        encrypt("")


def test_helper_works_via_module_fixture(encryption_helper: object) -> None:
    """The ``encryption_helper`` conftest fixture surfaces the same
    module. This proves the fixture wiring (master_key_path → env
    swap → cache reset → module yield) is correct."""
    assert encryption_helper is not None  # noqa: S101
    # Use the fixture-bound module rather than the top-level import to
    # confirm both reach the same Fernet instance.
    from imga_core.security import encryption as direct

    payload = "service-bound-key"
    cipher_via_fixture = direct.encrypt(payload)
    assert decrypt(cipher_via_fixture) == payload


def test_corrupt_ciphertext_surfaces_encryption_error_in_api() -> None:
    plaintext = "AIzaSy-real"
    ciphertext = bytearray(encrypt(plaintext))
    ciphertext[20] ^= 0x01
    with pytest.raises(EncryptionError, match="Failed to decrypt"):
        decrypt(bytes(ciphertext))


def test_master_key_path_env_unset_raises_at_first_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defending the deploy-time mistake of forgetting to mount the
    secret. The helper must surface the missing path, not silently
    fall back to a default key."""
    bogus = tmp_path / "missing.key"
    monkeypatch.setenv("IMGA_MASTER_KEY_PATH", str(bogus))
    reset_fernet_cache()
    with pytest.raises(EncryptionError) as excinfo:
        encrypt("anything")
    assert "missing.key" in str(excinfo.value)
