"""Sprint 9.5 D1 — api-worker healthcheck script regression.

The worker container has no HTTP surface, so docker's HEALTHCHECK
runs a Python script that opens a TCP socket to Redis and sends a
RESP PING. Exit 0 = healthy, non-zero = unhealthy. These tests
pin the success + failure paths without standing up a real Redis.
"""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from imga_api.workers.healthcheck import _check_redis


class _FakeSocket:
    """Minimal stdlib socket stand-in. Captures bytes the script
    writes and returns the bytes we hand it on recv."""

    def __init__(self, recv_bytes: bytes) -> None:
        self._recv = recv_bytes
        self.sent: bytes = b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def recv(self, _bufsize: int) -> bytes:
        return self._recv

    def __enter__(self) -> "_FakeSocket":
        return self

    def __exit__(self, *_args: Any) -> None:
        pass


def test_check_redis_returns_zero_on_pong() -> None:
    """Happy path: Redis answers ``+PONG\\r\\n`` (RESP simple
    string). Script exit code 0 → docker flips container to
    healthy."""
    fake = _FakeSocket(recv_bytes=b"+PONG\r\n")
    with patch(
        "imga_api.workers.healthcheck.socket.create_connection",
        return_value=fake,
    ):
        rc = _check_redis("redis://redis:6379/0", timeout_s=0.1)
    assert rc == 0
    # We also assert the script actually wrote a PING — without that
    # we'd be testing "the script returns 0 regardless of contract".
    assert fake.sent == b"PING\r\n"


def test_check_redis_returns_nonzero_when_socket_refuses() -> None:
    """Redis unreachable (container down, network partition) →
    socket.create_connection raises OSError → exit code 2.
    Docker flips the container to unhealthy and an operator gets
    paged."""
    with patch(
        "imga_api.workers.healthcheck.socket.create_connection",
        side_effect=OSError("connection refused"),
    ):
        rc = _check_redis("redis://redis:6379/0", timeout_s=0.1)
    assert rc == 2


def test_check_redis_returns_nonzero_on_unexpected_response() -> None:
    """Redis is reachable on the TCP layer but the response doesn't
    contain PONG (e.g. an L4 load balancer answering instead of
    Redis, or a misconfigured proxy). Defensive non-zero so we
    don't flag the container healthy when the worker actually
    can't enqueue."""
    fake = _FakeSocket(recv_bytes=b"-ERR not implemented\r\n")
    with patch(
        "imga_api.workers.healthcheck.socket.create_connection",
        return_value=fake,
    ):
        rc = _check_redis("redis://redis:6379/0", timeout_s=0.1)
    assert rc == 1


def test_check_redis_parses_custom_host_port() -> None:
    """REDIS_URL parsing: the script must pick up host + port from
    the URL, not hard-code ``redis:6379``. Operators with a tuned
    deployment (separate Redis instance, non-default port) rely on
    this."""
    captured_host: list[tuple[str, int]] = []

    def _fake_create_connection(
        addr: tuple[str, int], timeout: float
    ) -> _FakeSocket:
        captured_host.append(addr)
        return _FakeSocket(recv_bytes=b"+PONG\r\n")

    with patch(
        "imga_api.workers.healthcheck.socket.create_connection",
        side_effect=_fake_create_connection,
    ):
        rc = _check_redis("redis://other-host:6380/3", timeout_s=0.1)
    assert rc == 0
    assert captured_host == [("other-host", 6380)]
