import json
import shutil
import subprocess
from pathlib import Path

from amoscloud_ai.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in create_app().routes}


def test_standard_email_auth_routes_are_registered() -> None:
    paths = _paths()
    required = {
        "/auth/login",
        "/auth/login/request-code",
        "/auth/login/verify-code",
        "/auth/register/request-code",
        "/auth/register/verify",
        "/auth/password/forgot",
        "/auth/password/reset",
    }
    assert not (required - paths)


def test_login_page_exposes_one_complete_account_flow() -> None:
    html = (ROOT / "web" / "login.html").read_text(encoding="utf-8")
    for text in (
        "Sign in",
        "Create account",
        "Forgot password?",
        "Email me a sign-in code",
        "secure code on any device",
        "/static/account-access.js",
    ):
        assert text in html
    assert "Organization ID" not in html
    assert "Continue with GitHub" not in html
    assert "Forgot username" not in html
    assert "login-recovery.js" not in html
    assert "/static/unified-login.js" not in html


def test_account_access_uses_primary_email_routes() -> None:
    script = (ROOT / "web" / "account-access.js").read_text(encoding="utf-8")
    assert "window.prompt" not in script
    for route in (
        "/auth/login/request-code",
        "/auth/login/verify-code",
        "/auth/register/request-code",
        "/auth/register/verify",
        "/auth/password/forgot",
        "/auth/password/reset",
    ):
        assert route in script
    assert "/api/v1/auth/account-recovery/password/request" not in script
    assert "/api/v1/auth/account-recovery/username/request" not in script


def test_password_reset_code_field_only_shows_after_successful_request() -> None:
    node = shutil.which("node")
    if not node:  # pragma: no cover - only on hosts without Node.js
        return

    script = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');

function element(id) {
  const initiallyHidden = new Set(['name-field', 'new-password-field', 'email-code-field', 'password-hint']);
  const classes = new Set(initiallyHidden.has(id) ? ['hidden'] : []);
  return {
    id,
    value: '',
    required: false,
    disabled: false,
    hidden: false,
    textContent: '',
    className: '',
    autocomplete: '',
    listeners: {},
    focus() {},
    setAttribute() {},
    classList: {
      toggle(name, force) {
        if (force === undefined) {
          if (classes.has(name)) classes.delete(name); else classes.add(name);
        } else if (force) classes.add(name); else classes.delete(name);
      },
      contains(name) { return classes.has(name); },
    },
    addEventListener(type, fn) {
      this.listeners[type] = this.listeners[type] || [];
      this.listeners[type].push(fn);
    },
  };
}

async function runScenario(requestOk) {
  const ids = [
    'auth-form', 'name-field', 'identifier-field', 'password-field', 'new-password-field',
    'email-code-field', 'password-hint', 'name', 'identifier', 'password', 'new-password',
    'email-code', 'login-tab', 'register-tab', 'forgot-password-button',
    'submit-button', 'email-code-button', 'auth-title', 'auth-subtitle', 'message'
  ];
  const elements = Object.fromEntries(ids.map(id => [id, element(id)]));
  elements['auth-form'].reset = () => {
    for (const id of ['name', 'identifier', 'password', 'new-password', 'email-code']) {
      elements[id].value = '';
    }
  };
  elements['auth-form'].reportValidity = () => true;

  const calls = [];
  const fetch = async (url) => {
    calls.push(url);
    if (url === '/auth/password/forgot') {
      if (requestOk) {
        return {ok: true, status: 202, text: async () => JSON.stringify({message: 'Sent'})};
      }
      return {ok: false, status: 503, text: async () => JSON.stringify({detail: 'failure'})};
    }
    return {ok: true, status: 200, text: async () => '{}'};
  };

  const window = {
    location: {search: '', replace() {}},
  };
  const context = {
    window,
    document: {getElementById: id => elements[id] || null},
    fetch,
    URLSearchParams,
    JSON,
  };
  vm.runInNewContext(source, context);

  for (const fn of elements['forgot-password-button'].listeners.click || []) await fn({});
  const hiddenBefore = elements['email-code-field'].classList.contains('hidden');
  elements['identifier'].value = 'person@example.com';
  elements['new-password'].value = 'Secret12345!';
  for (const fn of elements['auth-form'].listeners.submit || []) {
    await fn({preventDefault() {}});
  }
  return {
    hiddenBefore,
    hiddenAfter: elements['email-code-field'].classList.contains('hidden'),
    requiredAfter: elements['email-code'].required,
    calls: calls.filter(url => url === '/auth/password/forgot').length,
  };
}

(async () => {
  process.stdout.write(JSON.stringify({
    success: await runScenario(true),
    failure: await runScenario(false),
  }));
})().catch(error => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
"""
    completed = subprocess.run(
        [node, "-e", script, str(ROOT / "web" / "account-access.js")],
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )
    result = json.loads(completed.stdout)

    assert result["success"]["hiddenBefore"] is True
    assert result["success"]["calls"] == 1
    assert result["success"]["hiddenAfter"] is False
    assert result["success"]["requiredAfter"] is True

    assert result["failure"]["hiddenBefore"] is True
    assert result["failure"]["calls"] == 1
    assert result["failure"]["hiddenAfter"] is True
    assert result["failure"]["requiredAfter"] is False


def test_registration_uses_the_visible_email_field() -> None:
    script = (ROOT / "web" / "account-access.js").read_text(encoding="utf-8")

    assert "name: inputs.name.value.trim()" in script
    assert "email: address" in script
    assert "password: inputs.nextPassword.value" in script
    assert "signupCodeRequested = true" in script
    assert "Verify and open Amosclaud" in script


def test_security_mail_sender_is_amosclaud_owned() -> None:
    source = (ROOT / "amoscloud_ai" / "mail_delivery.py").read_text(encoding="utf-8")
    assert "no-reply@amosclaud.com" in source
    assert 'endswith("@amosclaud.com")' in source
    assert "smtp.login" in source
    assert "print(" not in source


def test_primary_password_reset_revokes_existing_sessions() -> None:
    source = (ROOT / "amoscloud_ai" / "api" / "routes" / "auth.py").read_text(encoding="utf-8")
    assert '@router.post("/password/reset"' in source
    assert 'db.execute("DELETE FROM sessions WHERE user_id=?"' in source
    assert "Invalid or expired verification code" in source
