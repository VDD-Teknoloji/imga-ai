"""Generate a Fernet master key for tenant LLM credential encryption.

Sprint 8.3.6 / Alt-Faz 8.3.6.1.A. Writes a fresh URL-safe base64-encoded
32-byte key to the target path with mode 0600 so the secret never gets
world-readable. The encryption helper (``imga_core.security.encryption``)
mounts this file at ``/run/secrets/imga/master.key`` via Docker secrets
in production; locally the test compose mounts
``infra/imga/test/secrets/master.key`` with the same shape.

Usage (local test stack):

    python scripts/generate_master_key.py infra/imga/test/secrets/master.key

Usage (production, run as root on the host):

    sudo python3 scripts/generate_master_key.py /etc/imga-secrets/master.key

Losing this key invalidates every encrypted tenant LLM credential —
manual offline backup is the user's responsibility until Sprint 9.0+
introduces a vault.
"""

from __future__ import annotations

import pathlib
import sys

from cryptography.fernet import Fernet


def main(output_path: str) -> None:
    key = Fernet.generate_key()
    p = pathlib.Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(key)
    p.chmod(0o600)
    # stderr for the path so callers piping stdout get only the key.
    print(f"Master key written to {output_path}", file=sys.stderr)
    print(f"Key (base64): {key.decode()}", file=sys.stdout)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/etc/imga-secrets/master.key"
    main(target)
