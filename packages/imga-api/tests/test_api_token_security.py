"""security/api_tokens.py — saf helper testleri (DB gerektirmez).

Migration 0032 / N+1 auth dilimi. mint/hash/verify/prefix/env davranışını
doğrular; DB + RLS testleri ayrı (test_api_tokens_rls.py — sunucu handoff).
"""

from __future__ import annotations

import pytest

from imga_api.security.api_tokens import (
    OPS_LIVE_PREFIX,
    OPS_STG_PREFIX,
    TENANT_LIVE_PREFIX,
    TENANT_STG_PREFIX,
    extract_prefix,
    hash_token,
    is_ops_prefix,
    mint_token,
    token_environment,
    verify_token,
)

_PEPPER = "p" * 40


def test_mint_token_shape() -> None:
    t = mint_token(prefix=TENANT_LIVE_PREFIX, pepper=_PEPPER)
    assert t.plaintext.startswith(TENANT_LIVE_PREFIX)
    assert t.token_prefix == TENANT_LIVE_PREFIX
    assert t.last4 == t.plaintext[-4:]
    assert len(t.token_hash) == 64  # sha256 hex
    assert verify_token(t.plaintext, t.token_hash, _PEPPER)


def test_hash_deterministic_and_pepper_bound() -> None:
    plain = "imga_live_abc"
    assert hash_token(plain, _PEPPER) == hash_token(plain, _PEPPER)
    # farklı pepper → farklı hash (env başına ayrı pepper güvenliği)
    assert hash_token(plain, _PEPPER) != hash_token(plain, "q" * 40)


def test_verify_wrong_pepper_fails() -> None:
    t = mint_token(prefix=TENANT_LIVE_PREFIX, pepper=_PEPPER)
    assert not verify_token(t.plaintext, t.token_hash, "z" * 40)


def test_verify_wrong_plaintext_fails() -> None:
    t = mint_token(prefix=TENANT_LIVE_PREFIX, pepper=_PEPPER)
    assert not verify_token(t.plaintext + "x", t.token_hash, _PEPPER)


def test_mint_bodies_unique() -> None:
    a = mint_token(prefix=TENANT_LIVE_PREFIX, pepper=_PEPPER)
    b = mint_token(prefix=TENANT_LIVE_PREFIX, pepper=_PEPPER)
    assert a.plaintext != b.plaintext
    assert a.token_hash != b.token_hash


def test_extract_prefix_longest_match() -> None:
    assert extract_prefix("imga_ops_live_xxx") == OPS_LIVE_PREFIX
    assert extract_prefix("imga_ops_stg_xxx") == OPS_STG_PREFIX
    assert extract_prefix("imga_live_xxx") == TENANT_LIVE_PREFIX
    assert extract_prefix("imga_stg_xxx") == TENANT_STG_PREFIX
    assert extract_prefix("bogus_xxx") is None


def test_token_environment() -> None:
    assert token_environment("imga_live_x") == "live"
    assert token_environment("imga_ops_live_x") == "live"
    assert token_environment("imga_stg_x") == "stg"
    assert token_environment("imga_ops_stg_x") == "stg"
    assert token_environment("nope") is None


def test_is_ops_prefix() -> None:
    assert is_ops_prefix(OPS_LIVE_PREFIX)
    assert is_ops_prefix(OPS_STG_PREFIX)
    assert not is_ops_prefix(TENANT_LIVE_PREFIX)
    assert not is_ops_prefix(TENANT_STG_PREFIX)


def test_empty_pepper_rejected() -> None:
    with pytest.raises(ValueError):
        hash_token("imga_live_x", "")


def test_unknown_prefix_rejected() -> None:
    with pytest.raises(ValueError):
        mint_token(prefix="bogus_", pepper=_PEPPER)
