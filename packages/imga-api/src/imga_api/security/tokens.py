"""Cryptographically random invitation tokens.

Plaintext token returned to the caller exactly once, sent in the
invitation email link. Only the SHA-256 hash is stored in the DB;
acceptance requires hashing the link's token and looking up the row,
so a DB compromise alone cannot generate valid acceptances.
"""

from __future__ import annotations

import hashlib
import secrets

INVITATION_TOKEN_BYTES = 32  # 256-bit, ~43 chars urlsafe-base64


def generate_invitation_token() -> tuple[str, str]:
    """Return (plaintext_token, sha256_hex_hash).

    Send `plaintext_token` in the invitation link, persist `sha256_hex_hash`.
    """
    plaintext = secrets.token_urlsafe(INVITATION_TOKEN_BYTES)
    return plaintext, hash_token(plaintext)


def hash_token(plaintext: str) -> str:
    """Stable SHA-256 hex digest of an invitation token."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
