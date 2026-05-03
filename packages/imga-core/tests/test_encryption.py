"""Sprint 8.3.6 / Alt-Faz 8.3.6.1.C — Fernet encryption helper.

The helper is the only path tenant LLM API keys take to disk; if the
contract here breaks, every encrypted credential becomes either
plaintext-leaked or unrecoverable. Five tests pin the surface:

  1. round-trip — encrypt → decrypt yields the original string,
     including non-ASCII (Türkçe characters in the API key isn't a
     real risk, but the UTF-8 path needs proof).
  2. empty plaintext is rejected — Sprint 8.3.6.2's credential
     service is meant to fail loudly on a None API key bug instead
     of writing an authenticated token of an empty string.
  3. corrupt ciphertext raises EncryptionError — Fernet's auth
     check actually runs.
  4. missing key file raises EncryptionError — the helper doesn't
     fall back to a default key when the mount is wrong.
  5. cache reset behaviour — switching the master key path picks
     up the new file on the next call (the cache is opt-in, not
     a footgun).
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
def _isolated_master_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test master key + cache reset. Without this, the lru_cache
    leaks between tests and a key swap in test 5 silently uses the
    previous key — same class of bug Sprint 8.3.5.2 caught with
    migration version persistence."""
    key_path = tmp_path / "master.key"
    key_path.write_bytes(Fernet.generate_key())
    monkeypatch.setenv("IMGA_MASTER_KEY_PATH", str(key_path))
    reset_fernet_cache()
    yield key_path
    reset_fernet_cache()


def test_round_trip_preserves_plaintext_including_non_ascii() -> None:
    plaintext = "AIzaSy-örnek-key-with-ç-and-Ş-and-ı"
    ciphertext = encrypt(plaintext)
    assert isinstance(ciphertext, bytes)
    assert ciphertext != plaintext.encode("utf-8")
    assert decrypt(ciphertext) == plaintext


def test_empty_plaintext_raises_value_error() -> None:
    """An upstream None-coalesce bug must surface as ValueError
    rather than silently round-tripping ``""``."""
    with pytest.raises(ValueError, match="empty"):
        encrypt("")


def test_corrupt_ciphertext_raises_encryption_error() -> None:
    """Flipping a single byte breaks Fernet's HMAC; the helper must
    surface as EncryptionError, not bubble the raw InvalidToken."""
    plaintext = "real-api-key"
    ciphertext = bytearray(encrypt(plaintext))
    # Flip a byte deep inside the token (after the version + timestamp
    # so we hit the encrypted payload, not the framing).
    ciphertext[20] ^= 0x01
    with pytest.raises(EncryptionError, match="Failed to decrypt"):
        decrypt(bytes(ciphertext))


def test_missing_key_file_raises_encryption_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helper must not silently invent a key when the mount is
    wrong; the operator should see the exact path that's missing."""
    bogus = tmp_path / "definitely-not-here.key"
    monkeypatch.setenv("IMGA_MASTER_KEY_PATH", str(bogus))
    reset_fernet_cache()
    with pytest.raises(EncryptionError) as excinfo:
        encrypt("anything")
    # Substring check (Path str on Windows has backslashes the regex
    # match= helper can't escape automatically).
    assert "definitely-not-here.key" in str(excinfo.value)


def test_cache_reset_picks_up_new_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolated_master_key: Path
) -> None:
    """The lru_cache is a perf optimization, not a correctness contract.
    A test/tooling that swaps the key path mid-process must see the new
    key after ``reset_fernet_cache()`` — otherwise stale caches eat the
    fixture cleanup story."""
    plaintext = "first-key-payload"
    ciphertext_old = encrypt(plaintext)

    # Swap to a fresh key without resetting → still using the cached
    # Fernet, so decrypt of the OLD ciphertext still works.
    new_key_path = tmp_path / "new.key"
    new_key_path.write_bytes(Fernet.generate_key())
    monkeypatch.setenv("IMGA_MASTER_KEY_PATH", str(new_key_path))
    assert decrypt(ciphertext_old) == plaintext

    # Now reset; the next call binds to the new key. The OLD ciphertext
    # was signed by the OLD key → must fail auth.
    reset_fernet_cache()
    with pytest.raises(EncryptionError):
        decrypt(ciphertext_old)

    # And new encrypt/decrypt under the new key still works.
    ciphertext_new = encrypt(plaintext)
    assert decrypt(ciphertext_new) == plaintext


def test_helper_is_lazy_no_io_until_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity: the helper is lazy. Switching ``IMGA_MASTER_KEY_PATH``
    to an invalid path + clearing the cache must not raise on its own
    — the failure only surfaces when the first encrypt/decrypt
    actually runs. (No reload trick: that swaps EncryptionError class
    identity and confuses pytest.raises.)"""
    monkeypatch.setenv("IMGA_MASTER_KEY_PATH", "/nonexistent/path/key.bin")
    reset_fernet_cache()
    # Pre-call: cache cleared, env set to a bogus path, but no I/O yet.
    # Just assigning a no-op variable to prove this line runs.
    sentinel = "import-time should be silent"
    assert sentinel
    # Only when we actually try to use it do we get the error.
    with pytest.raises(EncryptionError):
        encrypt("foo")
