#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "amoscloud_ai/api/routes/owner_bootstrap.py"
AUTH = ROOT / "amoscloud_ai/api/routes/auth.py"
APPROVAL = ROOT / "amosclaud_bot/approval_gate.py"
ENV_EXAMPLE = ROOT / ".env.production.example"
TEST = ROOT / "tests/test_owner_oauth_and_private_data_approval.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"missing expected block: {label}")
    return text.replace(old, new, 1)


def patch_owner() -> None:
    text = OWNER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'def _github_headers(access_token: str) -> dict[str, str]:\n',
        '''def _send_github_redirect_uri() -> bool:\n    return os.getenv("GITHUB_ADMIN_SEND_REDIRECT_URI", "").strip().lower() in {\n        "1", "true", "yes", "on"\n    }\n\n\ndef _shared_cookie_domain() -> str | None:\n    return os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None\n\n\ndef _github_headers(access_token: str) -> dict[str, str]:\n''',
        "owner helpers",
    )
    text = replace_once(
        text,
        '''    callback = _github_admin_callback_url(request)\n    authorize_url = "https://github.com/login/oauth/authorize?" + urlencode(\n        {\n            "client_id": client_id,\n            "redirect_uri": callback,\n            "scope": "read:user user:email repo",\n            "state": state,\n            "allow_signup": "false",\n        }\n    )\n''',
        '''    callback = _github_admin_callback_url(request)\n    authorize_parameters = {\n        "client_id": client_id,\n        "scope": "read:user user:email repo",\n        "state": state,\n        "allow_signup": "false",\n    }\n    if _send_github_redirect_uri():\n        authorize_parameters["redirect_uri"] = callback\n    authorize_url = "https://github.com/login/oauth/authorize?" + urlencode(\n        authorize_parameters\n    )\n''',
        "authorization URL",
    )
    text = replace_once(
        text,
        '        samesite="lax",\n        path="/",\n    )\n    return response\n',
        '        samesite="lax",\n        path="/",\n        domain=_shared_cookie_domain(),\n    )\n    return response\n',
        "state cookie",
    )
    text = replace_once(
        text,
        '''    callback = _github_admin_callback_url(request)\n    async with httpx.AsyncClient(timeout=20) as client:\n        token_response = await client.post(\n            "https://github.com/login/oauth/access_token",\n            headers={"Accept": "application/json"},\n            data={\n                "client_id": client_id,\n                "client_secret": client_secret,\n                "code": code,\n                "redirect_uri": callback,\n            },\n        )\n''',
        '''    callback = _github_admin_callback_url(request)\n    token_parameters = {\n        "client_id": client_id,\n        "client_secret": client_secret,\n        "code": code,\n    }\n    if _send_github_redirect_uri():\n        token_parameters["redirect_uri"] = callback\n    async with httpx.AsyncClient(timeout=20) as client:\n        token_response = await client.post(\n            "https://github.com/login/oauth/access_token",\n            headers={"Accept": "application/json"},\n            data=token_parameters,\n        )\n''',
        "token exchange",
    )
    text = replace_once(
        text,
        '    response.delete_cookie(GITHUB_ADMIN_STATE_COOKIE, path="/")\n',
        '''    response.delete_cookie(\n        GITHUB_ADMIN_STATE_COOKIE, path="/", domain=_shared_cookie_domain()\n    )\n''',
        "state cleanup",
    )
    OWNER.write_text(text, encoding="utf-8")


def patch_auth_cookie() -> None:
    text = AUTH.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'def _set_session_cookie(response: Response, token: str) -> None:\n',
        '''def _cookie_domain() -> str | None:\n    return os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None\n\n\ndef _set_session_cookie(response: Response, token: str) -> None:\n''',
        "cookie helper",
    )
    text = replace_once(
        text,
        '        samesite="lax",\n        path="/",\n    )\n\n\ndef _create_session',
        '        samesite="lax",\n        path="/",\n        domain=_cookie_domain(),\n    )\n\n\ndef _create_session',
        "session cookie domain",
    )
    AUTH.write_text(text, encoding="utf-8")


def patch_approval() -> None:
    text = APPROVAL.read_text(encoding="utf-8")
    if "import re\n" not in text:
        text = text.replace("import hashlib\n", "import hashlib\nimport re\n", 1)
    text = re.sub(
        r'SENSITIVE_HINTS = \(.*?\)\n\nHIGH_RISK_PREFIXES = \(.*?\)\n\nHIGH_RISK_FILES = \{.*?\}\n',
        '''SENSITIVE_HINTS = (\n    "leaked secret",\n    "exposed secret",\n    "leaked key",\n    "exposed key",\n    "credential leak",\n    "password leak",\n    "private information",\n    "personal information",\n    "private data",\n    "recovery code leak",\n)\n\nPRIVATE_DATA_FILES = {\n    ".env", "secrets.json", "credentials.json",\n    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",\n}\nPRIVATE_DATA_SUFFIXES = (".pem", ".key", ".p12", ".pfx")\nPRIVATE_DATA_PATCH_MARKERS = (\n    "BEGIN PRIVATE KEY",\n    "BEGIN RSA PRIVATE KEY",\n    "BEGIN OPENSSH PRIVATE KEY",\n    "social security number",\n    "recovery phrase",\n)\n''',
        text,
        count=1,
        flags=re.DOTALL,
    )
    pattern = re.compile(
        r'def _high_risk_files\(files: list\[dict\[str, Any\]\]\) -> list\[str\]:\n.*?\n\n\ndef _path_is_outside_autonomous_boundary',
        re.DOTALL,
    )
    replacement = '''def _high_risk_files(files: list[dict[str, Any]]) -> list[str]:\n    """Require approval only for private information or credential material."""\n    findings: list[str] = []\n    for item in files:\n        paths = [str(item.get("filename") or "")]\n        previous = str(item.get("previous_filename") or "")\n        if previous:\n            paths.append(previous)\n        for raw_path in paths:\n            normalized = _normalize_repo_path(raw_path)\n            name = Path(normalized).name.lower()\n            if name in PRIVATE_DATA_FILES or name.endswith(PRIVATE_DATA_SUFFIXES):\n                findings.append(f"Private or credential-bearing file changed: `{normalized}`")\n        patch = str(item.get("patch") or "")\n        if any(marker in patch for marker in PRIVATE_DATA_PATCH_MARKERS):\n            filename = _normalize_repo_path(str(item.get("filename") or "unknown"))\n            findings.append(f"Potential private information detected in `{filename}`")\n    return list(dict.fromkeys(findings))\n\n\ndef _path_is_outside_autonomous_boundary'''
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError("approval classifier replacement failed")
    text = text.replace(
        'reason_lines=[f"High-risk path changed: `{name}`" for name in risky[:12]],',
        'reason_lines=risky[:12],',
    )
    text = text.replace(
        'f"Sensitive paths were detected. Approval issue: #{approval}"',
        'f"Private information or credential material was detected. Approval issue: #{approval}"',
    )
    text = text.replace(
        'f"Sensitive repair execution is paused. Approval issue: #{approval}"',
        'f"Private-data repair is paused. Approval issue: #{approval}"',
    )
    APPROVAL.write_text(text, encoding="utf-8")


def patch_env() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    marker = "GITHUB_ADMIN_CALLBACK_URL=https://www.amosclaud.com/api/v1/auth/github/admin-callback\n"
    addition = marker + "GITHUB_ADMIN_SEND_REDIRECT_URI=false\n"
    if addition not in text:
        text = text.replace(marker, addition, 1)
    ENV_EXAMPLE.write_text(text, encoding="utf-8")


def write_tests() -> None:
    TEST.write_text(
        '''from pathlib import Path\n\nfrom amosclaud_bot import approval_gate\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef read(path: str) -> str:\n    return (ROOT / path).read_text(encoding="utf-8")\n\n\ndef test_owner_oauth_uses_registered_callback_by_default() -> None:\n    source = read("amoscloud_ai/api/routes/owner_bootstrap.py")\n    assert "GITHUB_ADMIN_SEND_REDIRECT_URI" in source\n    assert 'authorize_parameters["redirect_uri"] = callback' in source\n    assert 'token_parameters["redirect_uri"] = callback' in source\n\n\ndef test_owner_cookies_work_across_www_and_apex_domains() -> None:\n    owner = read("amoscloud_ai/api/routes/owner_bootstrap.py")\n    auth = read("amoscloud_ai/api/routes/auth.py")\n    assert "domain=_shared_cookie_domain()" in owner\n    assert "domain=_cookie_domain()" in auth\n\n\ndef test_normal_code_and_workflow_repairs_do_not_need_approval() -> None:\n    files = [\n        {"filename": ".github/workflows/ci.yml", "patch": "+ model secret reference"},\n        {"filename": "amoscloud_ai/api/routes/auth.py", "patch": "+ login repair"},\n    ]\n    assert approval_gate._high_risk_files(files) == []\n    assert not approval_gate._is_sensitive_objective(\n        "fix the authentication workflow and permissions"\n    )\n\n\ndef test_private_information_changes_still_need_approval() -> None:\n    files = [\n        {"filename": ".env", "patch": "- removed private value"},\n        {"filename": "private.pem", "patch": "- removed credential material"},\n    ]\n    assert len(approval_gate._high_risk_files(files)) == 2\n    assert approval_gate._is_sensitive_objective(\n        "remove a leaked key from repository history"\n    )\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_owner()
    patch_auth_cookie()
    patch_approval()
    patch_env()
    write_tests()


if __name__ == "__main__":
    main()
