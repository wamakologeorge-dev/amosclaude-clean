from pathlib import Path
import json
import shutil
import subprocess

from amoscloud_ai.main import create_app


ROOT = Path(__file__).resolve().parents[1]


def _paths() -> set[str]:
    return {getattr(route, "path", "") for route in create_app().routes}


def test_account_recovery_routes_are_registered() -> None:
    paths = _paths()
    required = {
        "/api/v1/auth/account-recovery/email/request",
        "/api/v1/auth/account-recovery/email/verify",
        "/api/v1/auth/account-recovery/username/request",
        "/api/v1/auth/account-recovery/username/verify",
        "/api/v1/auth/account-recovery/password/request",
        "/api/v1/auth/account-recovery/password/reset",
    }
    assert not (required - paths)


def test_login_page_exposes_complete_account_access() -> None:
    html = (ROOT / "web" / "login.html").read_text(encoding="utf-8")
    for text in (
        "Create account",
        "Forgot password",
        "Forgot username",
        "Recovery email",
        "no-reply@amosclaud.com",
        "/static/account-access.js",
    ):
        assert text in html
    assert "login-recovery.js" not in html
    assert "/static/login.js" not in html


def test_account_access_uses_visible_recovery_flows() -> None:
    script = (ROOT / "web" / "account-access.js").read_text(encoding="utf-8")
    assert "window.prompt" not in script
    assert "/api/v1/auth/account-recovery/username/request" in script
    assert "/api/v1/auth/account-recovery/username/verify" in script
    assert "/api/v1/auth/account-recovery/password/request" in script
    assert "/api/v1/auth/account-recovery/password/reset" in script
    assert "/api/v1/auth/account-recovery/email/request" in script
    assert "/api/v1/auth/account-recovery/email/verify" in script


def test_password_recovery_code_field_only_shows_after_successful_request() -> None:
    node = shutil.which("node")
    if not node:  # pragma: no cover - only on hosts without Node.js
        return

    script = """
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync(process.argv[1], 'utf8');

function element(id) {
  const classes = new Set(id === 'email-code-field' || id === 'recovery-email-field' ? ['hidden'] : []);
  return {
    id,
    value: '',
    required: false,
    disabled: false,
    hidden: false,
    textContent: '',
    className: '',
    autocomplete: '',
    focus() {},
    listeners: {},
    classList: {
      toggle(name, force) {
        if (force === undefined) {
          if (classes.has(name)) classes.delete(name); else classes.add(name);
        } else if (force) {
          classes.add(name);
        } else {
          classes.delete(name);
        }
      },
      contains(name) {
        return classes.has(name);
      }
    },
    addEventListener(type, fn) {
      this.listeners[type] = this.listeners[type] || [];
      this.listeners[type].push(fn);
    },
  };
}

async function runScenario(passwordRequestOk) {
  const ids = [
    'auth-form', 'name-field', 'identifier-field', 'recovery-email-field', 'password-field',
    'new-password-field', 'email-code-field', 'password-hint', 'name', 'identifier',
    'recovery-email', 'password', 'new-password', 'email-code', 'login-tab', 'register-tab',
    'forgot-password-button', 'forgot-username-button', 'submit-button', 'email-code-button',
    'passkey-login-button', 'google-login-button', 'auth-title', 'auth-subtitle', 'message'
  ];
  const elements = Object.fromEntries(ids.map((id) => [id, element(id)]));
  elements['auth-form'].reset = () => {
    for (const id of ['name', 'identifier', 'recovery-email', 'password', 'new-password', 'email-code']) {
      elements[id].value = '';
    }
  };
  elements['auth-form'].reportValidity = () => true;

  const fetchCalls = [];
  const fetch = async (url) => {
    fetchCalls.push(url);
    if (url === '/api/v1/auth/google/status') {
      return {ok: true, status: 200, text: async () => JSON.stringify({enabled: false})};
    }
    if (url === '/api/v1/auth/account-recovery/password/request') {
      if (passwordRequestOk) {
        return {ok: true, status: 200, text: async () => JSON.stringify({message: 'Sent'})};
      }
      return {ok: false, status: 500, text: async () => JSON.stringify({detail: 'failure'})};
    }
    return {ok: true, status: 200, text: async () => '{}'};
  };

  const window = {
    location: {href: 'https://example.test/login', assign() {}, replace() {}},
    history: {replaceState() {}},
    isSecureContext: false,
  };

  const context = {
    window,
    navigator: {},
    document: {getElementById: (id) => elements[id] || null},
    fetch,
    URL,
    setTimeout: (fn) => fn(),
    clearTimeout: () => {},
    atob: (value) => Buffer.from(value, 'base64').toString('binary'),
    btoa: (value) => Buffer.from(value, 'binary').toString('base64'),
  };
  context.window.PublicKeyCredential = undefined;
  vm.runInNewContext(source, context);

  const click = async (id) => {
    for (const fn of elements[id].listeners.click || []) await fn({});
  };
  const submit = async () => {
    for (const fn of elements['auth-form'].listeners.submit || []) {
      await fn({preventDefault() {}});
    }
  };

  await click('forgot-password-button');
  const hiddenBeforeSubmit = elements['email-code-field'].classList.contains('hidden');
  elements['recovery-email'].value = 'person@example.com';
  await submit();
  return {
    hiddenBeforeSubmit,
    hiddenAfterSubmit: elements['email-code-field'].classList.contains('hidden'),
    codeRequiredAfterSubmit: elements['email-code'].required,
    requestCalls: fetchCalls.filter((url) => url === '/api/v1/auth/account-recovery/password/request').length,
  };
}

(async () => {
  const success = await runScenario(true);
  const failure = await runScenario(false);
  process.stdout.write(JSON.stringify({success, failure}));
})().catch((error) => {
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

    assert result["success"]["hiddenBeforeSubmit"] is True
    assert result["success"]["requestCalls"] == 1
    assert result["success"]["hiddenAfterSubmit"] is False
    assert result["success"]["codeRequiredAfterSubmit"] is True

    assert result["failure"]["hiddenBeforeSubmit"] is True
    assert result["failure"]["requestCalls"] == 1
    assert result["failure"]["hiddenAfterSubmit"] is True
    assert result["failure"]["codeRequiredAfterSubmit"] is False


def test_security_mail_sender_is_amosclaud_owned() -> None:
    source = (ROOT / "amoscloud_ai" / "mail_delivery.py").read_text(encoding="utf-8")
    assert "no-reply@amosclaud.com" in source
    assert 'endswith("@amosclaud.com")' in source
    assert "smtp.login" in source
    assert "print(" not in source


def test_password_recovery_revokes_existing_sessions() -> None:
    source = (ROOT / "amoscloud_ai" / "api" / "routes" / "account_recovery.py").read_text(encoding="utf-8")
    assert "DELETE FROM sessions WHERE user_id=?" in source
    assert "MAX_ATTEMPTS" in source
    assert "Invalid or expired verification code" in source
