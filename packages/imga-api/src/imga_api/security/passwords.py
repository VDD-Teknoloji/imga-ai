"""Argon2id password hashing.

argon2-cffi's PasswordHasher() defaults are stronger than the OWASP ASVS
2.4 minimums (argon2-cffi: time_cost=3, memory_cost=64MiB, parallelism=4
vs OWASP minimum t=3, m=12MiB, p=1). We use the defaults so future library
upgrades raise our floor automatically.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """Hash a plaintext password with argon2id."""
    if not plain:
        raise ValueError("password must not be empty")
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time verify; returns False on mismatch or any error."""
    if not plain or not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        # Malformed hash, unsupported algorithm, etc. Fail closed.
        return False


def needs_rehash(hashed: str) -> bool:
    """True when stored hash uses outdated parameters and should be re-hashed
    on the next successful login."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except Exception:
        return True
