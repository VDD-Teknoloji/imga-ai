"""Sprint 9.5 D1 — arq worker process healthcheck.

Runs as a sync Python script via container ``healthcheck: CMD``.
Exits 0 when Redis is reachable (the worker's primary external
dependency), non-zero otherwise. ``docker compose ps`` then flips
the container to ``healthy`` / ``unhealthy``, which an operator
or upstream orchestrator can act on.

Why not poll arq's internal state directly: arq doesn't expose a
stable inspection API across versions. Redis reachability is the
load-bearing dependency for the worker — if the worker can't talk
to Redis, every task in flight will fail and no new ones will be
picked up. That's the operationally interesting failure mode.

Why a Python script vs ``redis-cli`` healthcheck: the imga-api
container is python:slim and doesn't ship the redis-cli binary;
adding it bloats the image for one healthcheck. The stdlib socket
PING below stays at zero new deps.
"""

from __future__ import annotations

import os
import socket
import sys
from urllib.parse import urlparse


def _check_redis(url: str, *, timeout_s: float = 5.0) -> int:
    """Open a TCP socket to the Redis URL's host:port and send a
    minimal PING command. Returns 0 on PONG, non-zero on any
    connection / protocol failure. Best-effort — we don't speak
    RESP correctly enough to handle every Redis edge case, but
    PING/PONG is the most stable contract in the protocol."""
    parsed = urlparse(url)
    host = parsed.hostname or "redis"
    port = parsed.port or 6379
    try:
        with socket.create_connection(
            (host, port), timeout=timeout_s
        ) as sock:
            sock.sendall(b"PING\r\n")
            data = sock.recv(1024)
    except OSError:
        return 2
    if b"PONG" not in data:
        return 1
    return 0


def main() -> int:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return _check_redis(url)


if __name__ == "__main__":
    sys.exit(main())
