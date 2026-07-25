"""Tests for the workspace publish control and the vendored highlighter.

Covers the new owner-only PATCH /repositories/{id}/visibility endpoint and its
server-side authorization (owners only; private repositories stay invisible to
outsiders), the effect of publishing on read access, the vendored
dependency-free syntax highlighter, and the workspace chrome surfaces
(publish control, bound Autonomous buttons, provider identity). Also re-asserts
the not-found banner regression: the banner is driven only by the repository
metadata request, never by a tab or tree load.
"""

import asyncio
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from amoscloud_ai.api.routes import auth, repositories
from amoscloud_ai.main import create_app

WEB = Path(__file__).resolve().parent.parent / "web"
HIGHLIGHT_JS = WEB / "highlight.js"


def _mkuser(email: str):
    token = f"session-{email}"
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)"
            " VALUES (?,?,?,'password',0,?)",
            (email.split("@", 1)[0], email, auth._hash_password("pw"), now.isoformat()),
        )
        uid = cursor.lastrowid
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at)"
            " VALUES (?,?,?,?)",
            (
                auth._token_hash(token),
                uid,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return token, user


def _isolate(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")


def _request(method: str, token, url, body=None):
    async def run():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://ts") as client:
            if token:
                client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.request(method, url, json=body)

    return asyncio.run(run())


def _patch(token, url, body):
    return _request("PATCH", token, url, body)


def _get(token, url):
    return _request("GET", token, url)


def _visibility_of(rid: int) -> str:
    with repositories._db() as db:
        return db.execute(
            "SELECT visibility FROM repositories WHERE id=?", (rid,)
        ).fetchone()["visibility"]


# --- route registration ------------------------------------------------------


def test_visibility_route_is_registered_as_patch():
    app = create_app()
    methods = set()
    for route in app.routes:
        if getattr(route, "path", None) == "/api/v1/repositories/{repository_id}/visibility":
            methods |= getattr(route, "methods", None) or set()
    assert "PATCH" in methods


# --- owner can publish and unpublish ----------------------------------------


def test_owner_can_publish_repository(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    ).id

    response = _patch(token, f"/api/v1/repositories/{rid}/visibility", {"visibility": "public"})

    assert response.status_code == 200
    assert response.json()["visibility"] == "public"
    assert _visibility_of(rid) == "public"


def test_owner_can_make_repository_private_again(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="public"), owner
    ).id

    response = _patch(token, f"/api/v1/repositories/{rid}/visibility", {"visibility": "private"})

    assert response.status_code == 200
    assert response.json()["visibility"] == "private"
    assert _visibility_of(rid) == "private"


def test_publishing_actually_grants_read_access_to_other_users(tmp_path, monkeypatch):
    """The flag is not cosmetic: an outsider goes from 404 to 200."""
    _isolate(tmp_path, monkeypatch)
    owner_token, owner = _mkuser("owner@example.com")
    outsider, _ = _mkuser("outsider@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    ).id

    assert _get(outsider, f"/api/v1/repositories/{rid}").status_code == 404

    _patch(owner_token, f"/api/v1/repositories/{rid}/visibility", {"visibility": "public"})
    after = _get(outsider, f"/api/v1/repositories/{rid}")
    assert after.status_code == 200
    assert after.json()["visibility"] == "public"

    _patch(owner_token, f"/api/v1/repositories/{rid}/visibility", {"visibility": "private"})
    assert _get(outsider, f"/api/v1/repositories/{rid}").status_code == 404


# --- server-side authorization ----------------------------------------------


def test_collaborator_cannot_change_visibility(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _, owner = _mkuser("owner@example.com")
    dev_token, _ = _mkuser("dev@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    ).id
    repositories.add_collaborator(
        rid,
        repositories.CollaboratorRequest(email="dev@example.com", role="developer"),
        owner,
    )

    response = _patch(dev_token, f"/api/v1/repositories/{rid}/visibility", {"visibility": "public"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Owner access required"
    assert _visibility_of(rid) == "private"


def test_outsider_cannot_publish_private_repository_and_gets_no_leak(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _, owner = _mkuser("owner@example.com")
    outsider, _ = _mkuser("outsider@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="topsecret", visibility="private"), owner
    ).id

    response = _patch(outsider, f"/api/v1/repositories/{rid}/visibility", {"visibility": "public"})

    # 404, not 403: existence of a private repository is not disclosed.
    assert response.status_code == 404
    assert response.json()["detail"] == "Repository not found"
    assert "topsecret" not in response.text
    assert _visibility_of(rid) == "private"


def test_reader_of_public_repository_cannot_unpublish_it(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _, owner = _mkuser("owner@example.com")
    outsider, _ = _mkuser("outsider@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="public"), owner
    ).id

    response = _patch(outsider, f"/api/v1/repositories/{rid}/visibility", {"visibility": "private"})

    assert response.status_code == 403
    assert _visibility_of(rid) == "public"


def test_visibility_requires_authentication(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    ).id

    response = _patch(None, f"/api/v1/repositories/{rid}/visibility", {"visibility": "public"})

    assert response.status_code == 401
    assert _visibility_of(rid) == "private"


def test_visibility_rejects_unknown_values(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, owner = _mkuser("owner@example.com")
    rid = repositories.create_repository(
        repositories.RepositoryCreate(name="proj", visibility="private"), owner
    ).id

    response = _patch(token, f"/api/v1/repositories/{rid}/visibility", {"visibility": "world"})

    assert response.status_code == 422
    assert _visibility_of(rid) == "private"


def test_visibility_on_missing_repository_is_404(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    token, _ = _mkuser("owner@example.com")
    response = _patch(token, "/api/v1/repositories/999999/visibility", {"visibility": "public"})
    assert response.status_code == 404


# --- vendored highlighter: no third-party dependency -------------------------


def _code_without_comments(source: str) -> str:
    """Strip /* */ and // comments so prose cannot trip the dependency scan."""
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_highlighter_is_vendored_and_dependency_free():
    assert HIGHLIGHT_JS.exists(), "web/highlight.js must be vendored in the repo"
    code = _code_without_comments(HIGHLIGHT_JS.read_text(encoding="utf-8")).lower()
    for forbidden in ("http://", "https://", "unpkg", "jsdelivr", "cdnjs", "import(", "require(", "fetch("):
        assert forbidden not in code, f"highlighter must not reference {forbidden}"
    assert "amosclaudhighlight" in code


def test_highlighter_covers_the_required_languages():
    source = HIGHLIGHT_JS.read_text(encoding="utf-8")
    for language in ("python", "javascript", "json", "html", "css", "markdown", "shell", "yaml"):
        assert f"{language}:" in source, f"missing tokenizer for {language}"


def test_workspace_loads_vendored_highlighter_before_using_it():
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    assert "/static/highlight.js" in html
    assert html.index("/static/highlight.js") < html.index("/static/workspace.js")
    # No CDN script tags anywhere in the workspace page.
    assert not re.search(r'<script[^>]+src="https?://', html)


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is required to execute the highlighter")
def test_highlighter_escapes_hostile_file_content():
    """Untrusted file content must never become live markup."""
    payload = "<script>alert('xss')</script>\n<img src=x onerror=\"boom()\">"
    script = (
        f"const H=require({json.dumps(str(HIGHLIGHT_JS))});"
        "const langs=['python','javascript','json','html','css','markdown','shell','yaml','plain'];"
        f"const src={json.dumps(payload)};"
        "const out=langs.map(l=>H.highlight(src,l));"
        "console.log(JSON.stringify(out));"
    )
    rendered = json.loads(subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True
    ).stdout)
    assert rendered
    expected = (
        payload.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&#39;")
    )
    for html in rendered:
        assert "<script" not in html
        assert "<img" not in html
        # The only tags emitted are the highlighter's own spans...
        assert not re.search(r"</?(?!/?span\b)[a-zA-Z]", html)
        # ...and with those stripped, the payload survives fully escaped.
        assert re.sub(r"</?span[^>]*>", "", html) == expected


@pytest.mark.skipif(NODE is None, reason="node is required to execute the highlighter")
def test_highlighter_tokenizes_and_preserves_line_count():
    script = (
        f"const H=require({json.dumps(str(HIGHLIGHT_JS))});"
        "const r={};"
        "r.py=H.highlight('def f():\\n    return 1','python');"
        "r.js=H.highlight('const a = 1; // note','javascript');"
        "r.json=H.highlight('{\"k\": true}','json');"
        "r.lang=H.languageForPath('a/b/main.py');"
        "r.docstring=H.highlightLines('\\\"\\\"\\\"doc\\nmore\\\"\\\"\\\"\\nx=1','python');"
        "console.log(JSON.stringify(r));"
    )
    result = json.loads(subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, check=True
    ).stdout)

    assert '<span class="tok-keyword">def</span>' in result["py"]
    assert '<span class="tok-comment">// note</span>' in result["js"]
    assert '<span class="tok-prop">&quot;k&quot;</span>' in result["json"]
    assert result["lang"] == "python"
    # A docstring spanning two lines stays highlighted on both, and the line
    # count still matches the source so the gutter cannot drift.
    assert len(result["docstring"]) == 3
    assert all("tok-string" in line for line in result["docstring"][:2])


# --- workspace chrome surfaces ----------------------------------------------


def test_workspace_has_owner_publish_control():
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    assert 'id="ws-visibility"' in html
    assert 'id="ws-visibility-toggle"' in html
    # Hidden until the metadata response proves the viewer owns the repository.
    assert re.search(r'id="ws-visibility"[^>]*\shidden', html)

    js = (WEB / "workspace.js").read_text(encoding="utf-8")
    assert "/visibility" in js and "'PATCH'" in js
    assert "repository?.role === 'owner'" in js


def test_autonomous_buttons_are_bound_to_visible_controls():
    """Regression: listeners used to target hidden placeholder nodes."""
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    js = (WEB / "workspace.js").read_text(encoding="utf-8")
    for button in ("ws-agent-build", "ws-agent-test", "ws-agent-review", "ws-agent-deploy"):
        assert f'id="{button}"' in html
        assert button in js, f"{button} is rendered but never wired up"
    assert "ws-agent-output" in js
    # The dead placeholder block is gone.
    assert 'id="ws-build"' not in html
    assert 'id="ws-output"' not in html


def test_workspace_renders_provider_identity():
    html = (WEB / "workspace.html").read_text(encoding="utf-8")
    assert "Powered by" in html and "Amosclaud" in html


def test_tabs_autoload_once_and_cache():
    js = (WEB / "workspace.js").read_text(encoding="utf-8")
    assert "TAB_LOADERS" in js
    assert "if (!loader || tabLoaded[name]) return;" in js
    # A failed load is not cached, so revisiting the tab retries.
    assert "tabLoaded[name] = false;" in js
    for loader in ("loadCommits", "loadIssues", "loadPullRequests"):
        assert loader in js


def test_not_found_banner_is_only_driven_by_metadata_request():
    """Regression: the banner must not fire from tree/tab loads."""
    js = (WEB / "workspace.js").read_text(encoding="utf-8")
    # showNotFound is defined once and called exactly once, from the
    # repository-metadata failure path.
    assert js.count("function showNotFound()") == 1
    assert js.count("showNotFound();") == 1
    guard = "if (error.status === 404 || error.status === 403) { showNotFound(); return; }"
    assert guard in js
    # Successful metadata always clears it.
    assert "hideNotFound();" in js
    for loader in ("loadTree", "loadCommits", "loadIssues", "loadPullRequests"):
        body = js.split(f"async function {loader}(")[1].split("\n  }")[0]
        assert "showNotFound" not in body, f"{loader} must not raise the banner"
