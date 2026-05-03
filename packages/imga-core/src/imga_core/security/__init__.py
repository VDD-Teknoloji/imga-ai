"""Security primitives shared across imga packages.

Sprint 8.3.6 — Fernet symmetric encryption for tenant-scoped secrets
(LLM API keys today; expandable to other per-tenant credentials).
"""

from imga_core.security.encryption import (
    EncryptionError,
    decrypt,
    encrypt,
    reset_fernet_cache,
)

__all__ = [
    "EncryptionError",
    "decrypt",
    "encrypt",
    "reset_fernet_cache",
]
