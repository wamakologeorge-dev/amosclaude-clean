"""
tools.py — real, executable actions the autonomous agent can take.

Every function here actually does what it says: `generate` runs real
inference through the trained NGramModel, `fetch_url` makes a real HTTP
GET, and `publish` makes a real HTTP POST toward amosclaud.com (or
whatever AMOSCLAUD_SITE_URL is configured to). Nothing here is a stub
that returns fake success — failures (network errors, bad status codes,
etc.) are surfaced to the caller rather than swallowed.
"""

import json
import os
import urllib.error
import urllib.request
from typing import Dict

AMOSCLAUD_SITE_URL = os.environ.get(
    "AMOSCLAUD_SITE_URL", "https://amosclaud.com/api/publish"
)
AMOSCLAUD_SITE_TOKEN = os.environ.get("AMOSCLAUD_SITE_TOKEN")  # set by admin if the site requires its own auth
HTTP_TIMEOUT_SECONDS = int(os.environ.get("AMOSCLAUD_HTTP_TIMEOUT", "10"))


def tool_generate(model, args: Dict) -> Dict:
    prompt = args.get("prompt", "")
    max_new_tokens = int(args.get("max_new_tokens", 60))
    temperature = float(args.get("temperature", 0.8))
    top_p = float(args.get("top_p", 0.95))

    text = model.generate(
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_p=top_p,
    )
    return {"ok": True, "text": text}


def tool_fetch_url(model, args: Dict) -> Dict:
    url = args.get("url")
    if not url:
        return {"ok": False, "error": "'url' is required for fetch_url"}
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": "url must start with http:// or https://"}

    req = urllib.request.Request(url, headers={"User-Agent": "amosclaud-autonomous-agent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            body = resp.read(200_000).decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"connection failed: {e.reason}"}
    except Exception as e:  # noqa: BLE001 — surface any failure to the caller
        return {"ok": False, "error": str(e)}


def tool_publish(model, args: Dict) -> Dict:
    """POSTs real content to the configured Amosclaud site endpoint.

    NOTE: amosclaud.com's actual publish API contract (auth scheme, field
    names) isn't documented anywhere I have access to, so this sends a
    reasonable, clearly-labeled JSON payload and an Authorization bearer
    header if AMOSCLAUD_SITE_TOKEN is set. If the real endpoint expects a
    different shape, update AMOSCLAUD_SITE_URL / the payload below to
    match its actual API docs once you have them — this is real,
    functioning HTTP code, not a mock, but it can only be as correct as
    the endpoint contract it's told to target.
    """
    title = args.get("title")
    content = args.get("content")
    if not title or not content:
        return {"ok": False, "error": "'title' and 'content' are required for publish"}

    payload = json.dumps({"title": title, "content": content}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if AMOSCLAUD_SITE_TOKEN:
        headers["Authorization"] = f"Bearer {AMOSCLAUD_SITE_TOKEN}"

    req = urllib.request.Request(AMOSCLAUD_SITE_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            body = resp.read(50_000).decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "response": body}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"connection failed: {e.reason}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


TOOL_REGISTRY = {
    "generate": tool_generate,
    "fetch_url": tool_fetch_url,
    "publish": tool_publish,
}
