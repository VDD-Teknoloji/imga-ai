"""Opak API token üretimi + doğrulaması (İmga v1 partner API, contract §8/§8.1).

Kiracı token'ları ``imga_live_`` / ``imga_stg_``; ops (admin) token'ları
``imga_ops_live_`` / ``imga_ops_stg_`` önekli (Stripe ``sk_live_``/``sk_test_``
deseni). Gövde 32-byte urlsafe random. At-rest YALNIZ HMAC-SHA256(pepper) hex
saklanır — plaintext asla DB'de durmaz (Invitation token deseni;
imga_api.security.tokens).

Pepper (``IMGA_TOKEN_PEPPER``) fonksiyonlara AÇIKÇA geçilir: saf + test
edilebilir, import-time secret yok. HMAC (düz SHA-256 değil) pepper'sız offline
sözlük saldırısını engeller; Argon2'den hızlı → auth sıcak yolu için uygun.

Cross-env enforcement (§8.1): ``token_environment()`` önekten live/stg çıkarır;
auth katmanı token ortamı ≠ sunucu ortamı ise 401 ``wrong_environment`` döner.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Literal

API_TOKEN_BYTES = 32  # 256-bit gövde, ~43 char urlsafe-base64

# Stripe-style önekler.
TENANT_LIVE_PREFIX = "imga_live_"
TENANT_STG_PREFIX = "imga_stg_"
OPS_LIVE_PREFIX = "imga_ops_live_"
OPS_STG_PREFIX = "imga_ops_stg_"

# extract_prefix en-uzun-önce dener (ops önekleri daha uzun); hiçbir önek
# diğerinin öneki olmadığı için sıra güvenlik için değil netlik için.
_KNOWN_PREFIXES: tuple[str, ...] = (
    OPS_LIVE_PREFIX,
    OPS_STG_PREFIX,
    TENANT_LIVE_PREFIX,
    TENANT_STG_PREFIX,
)

Environment = Literal["live", "stg"]


@dataclass(frozen=True, slots=True)
class MintedToken:
    """``mint_token()`` çıktısı. ``plaintext`` YALNIZ create/rotate yanıtında
    döner; DB'ye ``token_hash`` + ``token_prefix`` + ``last4`` yazılır."""

    plaintext: str
    token_hash: str
    token_prefix: str
    last4: str


def hash_token(plaintext: str, pepper: str) -> str:
    """HMAC-SHA256(pepper, plaintext) hex — at-rest saklanan tek temsil."""
    if not pepper:
        # Boş pepper = yanlış yapılandırma; sessizce zayıf hash üretme.
        raise ValueError("pepper must not be empty")
    return hmac.new(
        pepper.encode("utf-8"), plaintext.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_token(plaintext: str, stored_hash: str, pepper: str) -> bool:
    """Sabit-zaman karşılaştırma (timing attack'a karşı)."""
    return hmac.compare_digest(hash_token(plaintext, pepper), stored_hash)


def mint_token(*, prefix: str, pepper: str) -> MintedToken:
    """Verilen önekle yeni token üret. ``prefix`` bilinen öneklerden biri
    olmalı; gövde kriptografik rastgele."""
    if prefix not in _KNOWN_PREFIXES:
        raise ValueError(f"unknown token prefix: {prefix!r}")
    plaintext = f"{prefix}{secrets.token_urlsafe(API_TOKEN_BYTES)}"
    return MintedToken(
        plaintext=plaintext,
        token_hash=hash_token(plaintext, pepper),
        token_prefix=prefix,
        last4=plaintext[-4:],
    )


def extract_prefix(plaintext: str) -> str | None:
    """Token'ın önekini döndür (en-uzun-eşleşme) ya da None (tanınmayan)."""
    for prefix in _KNOWN_PREFIXES:
        if plaintext.startswith(prefix):
            return prefix
    return None


def token_environment(plaintext: str) -> Environment | None:
    """Önekten ortamı çıkar: ``live`` | ``stg`` | None. Cross-env
    enforcement (§8.1): token ortamı ≠ sunucu ortamı → 401 wrong_environment."""
    prefix = extract_prefix(plaintext)
    if prefix in (TENANT_LIVE_PREFIX, OPS_LIVE_PREFIX):
        return "live"
    if prefix in (TENANT_STG_PREFIX, OPS_STG_PREFIX):
        return "stg"
    return None


def is_ops_prefix(prefix: str) -> bool:
    """Ops (admin) önekleri: ``imga_ops_*``. opsBearer ayrımı (§8.6)."""
    return prefix in (OPS_LIVE_PREFIX, OPS_STG_PREFIX)


__all__ = [
    "API_TOKEN_BYTES",
    "TENANT_LIVE_PREFIX",
    "TENANT_STG_PREFIX",
    "OPS_LIVE_PREFIX",
    "OPS_STG_PREFIX",
    "Environment",
    "MintedToken",
    "hash_token",
    "verify_token",
    "mint_token",
    "extract_prefix",
    "token_environment",
    "is_ops_prefix",
]
