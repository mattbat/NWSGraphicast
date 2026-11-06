"""SMTP delivery."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage


def send_email(
    msg: EmailMessage,
    *,
    user: str,
    password: str,
    host: str = "smtp.gmail.com",
    port: int = 465,
    timeout: float = 30.0,
) -> None:
    with smtplib.SMTP_SSL(
        host, port, context=ssl.create_default_context(), timeout=timeout
    ) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
