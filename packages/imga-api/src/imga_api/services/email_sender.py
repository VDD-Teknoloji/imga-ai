"""SMTP transport — email_outbox dispatcher'ının tek gönderim yolu.

Env sözleşmesi (scheduled_briefings'in IMGA_SMTP_HOST gate'ini
genişletir):

    IMGA_SMTP_HOST       (boşsa gönderim kapalı — is_configured False)
    IMGA_SMTP_PORT       (default 587)
    IMGA_SMTP_USERNAME   (boşsa login atlanır)
    IMGA_SMTP_PASSWORD
    IMGA_SMTP_FROM       (default no-reply@imga.ai)
    IMGA_SMTP_FROM_NAME  (default İmga)
    IMGA_SMTP_STARTTLS   (default true)

smtplib senkron — yeni bağımlılık eklememek için aiosmtplib yerine
``asyncio.to_thread`` ile event loop dışına alınır.
"""

from __future__ import annotations

import asyncio
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

_TRUTHY = {"1", "true", "yes", "on"}
_SMTP_TIMEOUT_SECONDS = 30.0


def is_configured() -> bool:
    return bool(os.environ.get("IMGA_SMTP_HOST", "").strip())


def _send_sync(*, to_email: str, subject: str, body_text: str) -> None:
    host = os.environ.get("IMGA_SMTP_HOST", "").strip()
    port = int(os.environ.get("IMGA_SMTP_PORT", "587"))
    username = os.environ.get("IMGA_SMTP_USERNAME", "").strip()
    password = os.environ.get("IMGA_SMTP_PASSWORD", "")
    from_addr = os.environ.get("IMGA_SMTP_FROM", "no-reply@imga.ai").strip()
    from_name = os.environ.get("IMGA_SMTP_FROM_NAME", "İmga").strip()
    starttls = (
        os.environ.get("IMGA_SMTP_STARTTLS", "true").strip().lower()
        in _TRUTHY
    )

    message = EmailMessage()
    message["From"] = formataddr((from_name, from_addr))
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body_text)

    with smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
        if starttls:
            smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


async def send_email(*, to_email: str, subject: str, body_text: str) -> None:
    """Tek e-posta gönder; SMTP hatasını çağırana fırlatır (dispatcher
    attempts/backoff muhasebesini kendisi yapar)."""
    await asyncio.to_thread(
        _send_sync, to_email=to_email, subject=subject, body_text=body_text
    )


__all__ = [
    "is_configured",
    "send_email",
]
