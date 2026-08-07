"""HTML pages for Amosclaud account sign-in and OAuth consent."""

from __future__ import annotations

import sqlite3
from html import escape

from .oauth_config import OAUTH_PATH


def consent_html(
    *,
    user: sqlite3.Row,
    request_id: str,
    client_name: str,
    scopes: list[str],
) -> str:
    scope_items = "".join(f"<li><code>{escape(scope)}</code></li>" for scope in scopes)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Connect Amosclaud</title>
  <style>
    body{{font-family:system-ui,sans-serif;background:#f5f7fb;color:#111;margin:0;padding:2rem}}
    main{{max-width:620px;margin:auto;background:white;border:1px solid #dfe3ea;border-radius:18px;padding:2rem}}
    h1{{margin-top:0}} code{{background:#eef2f7;padding:.15rem .35rem;border-radius:5px}}
    .actions{{display:flex;gap:.75rem;margin-top:1.5rem}} button{{padding:.8rem 1.1rem;border-radius:10px;border:1px solid #bbb}}
    .approve{{background:#111;color:white;border-color:#111}}
  </style>
</head>
<body><main>
  <p><strong>AMOSCLAUD ACCOUNT CONNECTOR</strong></p>
  <h1>Connect {escape(client_name)}</h1>
  <p>Signed in as <strong>{escape(str(user["email"]))}</strong>.</p>
  <p>This app is requesting the following Amosclaud account permissions:</p>
  <ul>{scope_items}</ul>
  <p>The connector can use write permissions to create, update, repair, deploy, or remove
  resources through Amosclaud. The client may still show its own action confirmation.</p>
  <form method="post" action="{OAUTH_PATH}/authorize">
    <input type="hidden" name="request_id" value="{escape(request_id)}">
    <div class="actions">
      <button class="approve" type="submit" name="decision" value="approve">Connect Amosclaud</button>
      <button type="submit" name="decision" value="deny">Cancel</button>
    </div>
  </form>
</main></body></html>"""


def login_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Sign in to connect Amosclaud</title>
  <style>
    body{font-family:system-ui,sans-serif;background:#f5f7fb;margin:0;padding:2rem}
    main{max-width:520px;margin:auto;background:white;padding:2rem;border-radius:18px;border:1px solid #ddd}
    label{display:block;margin:.9rem 0} input{box-sizing:border-box;width:100%;padding:.8rem}
    button{padding:.8rem 1.1rem;background:#111;color:white;border:0;border-radius:10px}
    #message{min-height:1.3rem;color:#b42318}
  </style>
</head>
<body><main>
  <p><strong>AMOSCLAUD ACCOUNT CONNECTOR</strong></p>
  <h1>Sign in to Amosclaud</h1>
  <p>Sign in here, then Amosclaud will show the connector permissions.</p>
  <form id="login">
    <label>Email or username<input id="account" autocomplete="username" required></label>
    <label>Password<input id="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Sign in and continue</button>
  </form>
  <p id="message"></p>
</main>
<script>
const form=document.getElementById("login");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const account=document.getElementById("account").value.trim().toLowerCase();
  const email=account.includes("@") ? account : `${account}@amosclaud.com`;
  const response=await fetch("/api/v1/auth/login", {
    method:"POST", credentials:"same-origin",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({email, password:document.getElementById("password").value})
  });
  if(response.ok) window.location.reload();
  else {
    let detail="Sign in failed";
    try { detail=(await response.json()).detail || detail; } catch (_) {}
    document.getElementById("message").textContent=detail;
  }
});
</script></body></html>"""
