"""Amosclaud HTTPS mail transport contract.

Railway blocks outbound SMTP ports, so account-security email must be able
to travel over HTTPS (Resend API) when RESEND_API_KEY is configured.
"""
import json

import pytest

from amoscloud_ai import mail_http
from amoscloud_ai.mail_http import HttpMailError, deliver_via_http, http_mail_configured


def test_http_mail_not_configured_without_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert http_mail_configured() is False
    with pytest.raises(HttpMailError):
        deliver_via_http("no-reply@amosclaud.com", "user@example.com", "Subject", "Body")


def test_http_mail_configured_with_key(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    assert http_mail_configured() is True


def test_deliver_via_http_posts_resend_payload(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr(mail_http.urllib.request, "urlopen", fake_urlopen)
    deliver_via_http("no-reply@amosclaud.com", "user@example.com", "Verify", "Code 123456")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer re_test_key"
    assert captured["payload"]["from"] == "no-reply@amosclaud.com"
    assert captured["payload"]["to"] == ["user@example.com"]
    assert captured["payload"]["subject"] == "Verify"
    assert "123456" in captured["payload"]["text"]


def test_deliver_via_http_wraps_network_errors(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")

    def fake_urlopen(request, timeout=0):
        raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(mail_http.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(HttpMailError):
        deliver_via_http("no-reply@amosclaud.com", "user@example.com", "Verify", "Body")


def test_security_mail_prefers_https_when_configured(monkeypatch):
    from amoscloud_ai import mail_delivery

    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("MAIL_SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    sent = {}

    def fake_deliver(sender, recipient, subject, body):
        sent["sender"] = sender
        sent["recipient"] = recipient

    monkeypatch.setattr(mail_delivery, "deliver_via_http", fake_deliver)
    mail_delivery.deliver_security_code("user@example.com", "123456", "register")
    assert sent["recipient"] == "user@example.com"
    assert sent["sender"].lower().endswith("@amosclaud.com")
