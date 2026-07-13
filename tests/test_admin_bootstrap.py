from amoscloud_ai.admin_bootstrap import configured_admin_emails, should_grant_admin


def test_default_administrator_email_allowlist(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("AMOSCLAUD_ALLOW_FIRST_USER_ADMIN", raising=False)

    assert configured_admin_emails() == {
        "georgemakulu@amosclaud.com",
        "wamakologeorge@gmail.com",
    }
    assert should_grant_admin("georgemakulu@amosclaud.com", is_first_user=False)
    assert should_grant_admin("WAMAKOLOGEORGE@GMAIL.COM", is_first_user=False)


def test_first_unlisted_user_is_not_automatically_admin(monkeypatch):
    monkeypatch.delenv("AMOSCLAUD_ADMIN_EMAILS", raising=False)
    monkeypatch.delenv("AMOSCLAUD_ALLOW_FIRST_USER_ADMIN", raising=False)

    assert not should_grant_admin("attacker@example.com", is_first_user=True)


def test_operator_can_override_admin_allowlist(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_ADMIN_EMAILS", "owner@example.com, backup@example.com")
    monkeypatch.delenv("AMOSCLAUD_ALLOW_FIRST_USER_ADMIN", raising=False)

    assert should_grant_admin("owner@example.com", is_first_user=False)
    assert should_grant_admin("backup@example.com", is_first_user=False)
    assert not should_grant_admin("georgemakulu@amosclaud.com", is_first_user=False)


def test_explicit_self_hosted_first_user_bootstrap(monkeypatch):
    monkeypatch.setenv("AMOSCLAUD_ADMIN_EMAILS", "")
    monkeypatch.setenv("AMOSCLAUD_ALLOW_FIRST_USER_ADMIN", "true")

    assert should_grant_admin("owner@private.local", is_first_user=True)
    assert not should_grant_admin("second@private.local", is_first_user=False)
