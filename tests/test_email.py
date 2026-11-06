from email.message import EmailMessage

import pytest

from graphicast.notify import email as notify_email


class FakeSMTP:
    instances: list = []

    def __init__(self, host, port, context=None, timeout=None):
        self.args = (host, port, timeout)
        self.context = context
        self.calls = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append(("send", msg))


def test_send_email(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(notify_email.smtplib, "SMTP_SSL", FakeSMTP)
    msg = EmailMessage()
    notify_email.send_email(msg, user="u", password="p")
    smtp = FakeSMTP.instances[0]
    assert smtp.args == ("smtp.gmail.com", 465, 30.0)
    assert smtp.context is not None
    assert smtp.calls == [("login", "u", "p"), ("send", msg)]


def test_send_email_propagates_errors(monkeypatch):
    class Boom(FakeSMTP):
        def login(self, user, password):
            raise OSError("auth")

    monkeypatch.setattr(notify_email.smtplib, "SMTP_SSL", Boom)
    with pytest.raises(OSError):
        notify_email.send_email(EmailMessage(), user="u", password="p")
