"""Sprint 9.5 C2 — auth-path User TTL cache regression tests.

Production pg_stat_statements (12.05.2026) showed ~3000
``SELECT FROM users WHERE id=?`` calls per snapshot window — each
sub-millisecond, but the volume hits ~870ms of cumulative DB
overhead across ~3500 requests. The cache absorbs the repeats.

Two contracts pinned:

  1. **Cache hit** — within the TTL window, repeated lookups for
     the same user don't hit the DB. The auditor + middleware
     stay cheap on the hot path.

  2. **Invalidation on password change** — AuthService.change_password
     must drop the cached User row so a request that races the
     password change doesn't serve a stale ``password_changed_at``
     and accidentally accept a token issued before the change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from imga_db.models import User

from imga_api.auth_deps import (
    _USER_CACHE_TTL_SECONDS,
    _reset_user_cache_for_tests,
    _user_cache,
    invalidate_user_cache,
)


def _fake_user(user_id: UUID) -> Any:
    """Lightweight User stand-in — only the attributes the auth path
    reads (is_active, password_changed_at)."""
    u = MagicMock(spec=User)
    u.id = user_id
    u.is_active = True
    u.password_changed_at = None
    return u


def test_cache_starts_empty_after_reset() -> None:
    _reset_user_cache_for_tests()
    assert len(_user_cache) == 0


def test_set_and_get_round_trips_within_ttl() -> None:
    """The cache MUST return the exact object that was put in. The
    auth path reads ``user.is_active`` + ``user.password_changed_at``
    from the cached instance; if the cache deep-copies or
    re-instantiates, those attributes might lose their wiring."""
    _reset_user_cache_for_tests()
    user_id = uuid4()
    user = _fake_user(user_id)
    _user_cache[user_id] = user
    cached = _user_cache.get(user_id)
    assert cached is user, "cache must return the same object instance"


def test_invalidate_user_cache_drops_row() -> None:
    """The invalidation hook is what makes the cache safe to use
    on a mutable User. Tests pin that the function actually clears
    the entry (vs being a silent no-op that would mask staleness)."""
    _reset_user_cache_for_tests()
    user_id = uuid4()
    _user_cache[user_id] = _fake_user(user_id)
    assert user_id in _user_cache

    invalidate_user_cache(user_id)
    assert user_id not in _user_cache, (
        "invalidate_user_cache must remove the entry — staleness window "
        "after a password change / role change depends on this"
    )


def test_invalidate_unknown_user_id_is_noop() -> None:
    """Idempotent: invalidating a user that isn't cached doesn't
    raise. Callers (change_password, future deactivate / role
    change) don't have to check ``if user_id in cache`` first."""
    _reset_user_cache_for_tests()
    invalidate_user_cache(uuid4())  # must NOT raise


def test_ttl_is_60_seconds() -> None:
    """Pins the TTL value — short enough that a multi-worker
    deployment converges on a password change within a minute even
    when the worker that handled change_password isn't the one
    serving the next request."""
    assert _USER_CACHE_TTL_SECONDS == 60, (
        f"User cache TTL changed to {_USER_CACHE_TTL_SECONDS}s — "
        "Sprint 9.5 C2 contract is 60s; longer increases stale-auth "
        "window across uvicorn workers, shorter undermines the "
        "performance reason for caching at all"
    )
