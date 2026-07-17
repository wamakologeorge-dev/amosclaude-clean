# Amosclaud Autonomous

An agent server that plans and executes multi-step tasks on its own, using
its own built-in model — no third-party LLM API key required anywhere.
Access to *this server's own API* is gated by admin-issued "Amosclaud
keys." This project is verified working end-to-end (see "Tested" below).

## How auth works

- **No external API key needed to run the agent.** It reasons using the
  same local, zero-dependency n-gram model as the base
  [Amosclaud model server](../amosclaud-server) — trained from
  `corpus.txt` at startup, entirely offline.
- **Only an admin can create Amosclaud keys.** There is no signup
  endpoint and no self-service key creation over HTTP. Keys are created
  exclusively via `manage_keys.py`, which requires shell access to the
  machine running the server.
- **Keys are never stored in plaintext.** `manage_keys.py create` shows
  you the plaintext key exactly once. What's saved to `keys.json` is a
  salted SHA-256 hash — if that file leaks, the keys inside it can't be
  reconstructed.
- **Every request to `/agent/*` requires a valid key** in the
  `X-Amosclaud-Key` header. `/health` is the only open route.

## Setup

```bash
pip install -r requirements.txt

# Admin creates the first key (do this once, keep the output safe):
python manage_keys.py create "my first key"
#   Key created. This is the ONLY time the plaintext key is shown —
#   store it now; it cannot be recovered later.
#     key : amcl_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

## Run

```bash
python app.py
```

Starts on `http://localhost:8001` by default.

## Managing keys

```bash
python manage_keys.py create "label"   # issue a new key (shown once)
python manage_keys.py list             # see id / label / created / status — never the key itself
python manage_keys.py revoke <id>      # immediately locks that key out
```

## Using the agent

### `GET /health` — no key required
```bash
curl http://localhost:8001/health
```

### `POST /agent/run` — requires `X-Amosclaud-Key`

**Autonomous mode** — give it a goal, it plans and executes on its own:
```bash
curl -X POST http://localhost:8001/agent/run \
  -H "Content-Type: application/json" \
  -H "X-Amosclaud-Key: amcl_..." \
  -d '{"goal": "Explain concurrency"}'
```

**Explicit mode** — you supply the exact steps, the agent just executes them:
```bash
curl -X POST http://localhost:8001/agent/run \
  -H "Content-Type: application/json" \
  -H "X-Amosclaud-Key: amcl_..." \
  -d '{
        "steps": [
          {"tool": "generate", "args": {"prompt": "A database stores", "max_new_tokens": 20}},
          {"tool": "fetch_url", "args": {"url": "https://example.com"}}
        ]
      }'
```

`max_steps` (default 10, hard cap 25) bounds how many tool calls a run can
make, so a plan can't loop forever.

### `GET /agent/tools` — requires `X-Amosclaud-Key`
Lists the tools the agent can call and their arguments.

## How planning actually works

`planner.py`'s `auto_plan()` is a real, rule-based planner — not a call
out to a large reasoning model. It looks for concrete signals in the goal
text (a URL present → fetch it and summarize; the word "publish" →
generate content and publish it; otherwise → just generate a response)
and builds a step list from that. This is genuinely autonomous — nothing
about the plan is hand-picked by a human per-request — but it's honest
about being a simple dispatcher rather than claiming LLM-grade planning.
If you want smarter planning, this is the function to swap out.

## Belonging to amosclaud.com

The `publish` tool (`tools.py`) makes a real HTTP POST toward
`AMOSCLAUD_SITE_URL` (defaults to `https://amosclaud.com/api/publish`)
with a JSON body of `{"title": ..., "content": ...}`, and an
`Authorization: Bearer` header if `AMOSCLAUD_SITE_TOKEN` is set.

**Important caveat:** I don't have access to amosclaud.com's actual API
documentation (auth scheme, exact field names, response shape), so this
is real, functioning HTTP code sending a reasonable payload — not a mock
— but it can only be as correct as the endpoint contract it's pointed at.
Once you have amosclaud.com's real publish API docs, update
`tool_publish()` in `tools.py` to match the exact fields it expects.

```bash
export AMOSCLAUD_SITE_URL="https://amosclaud.com/api/publish"
export AMOSCLAUD_SITE_TOKEN="whatever-token-the-site-issues-you"
```

`/health` also reports `"belongs_to": "https://amosclaud.com"` so the
agent self-identifies its home site in its own status output.

## Tested

Every claim above was actually exercised against a running instance of
this server in this environment, not just read for syntax errors:

- `manage_keys.py create` → confirmed only a salted hash lands in
  `keys.json`, never the plaintext key
- `/agent/run` with no key → real `401`
- `/agent/run` with a wrong key → real `401`
- `/agent/run` with a valid key, auto-planned goal → real generated text
  from the trained model
- `/agent/run` with an explicit multi-step plan → both steps executed in
  order, real output for each
- `/agent/run` with an unknown tool name → real error in the transcript,
  execution stops rather than pretending to continue
- `fetch_url` against a real external host → a real HTTP status/error was
  returned (not a canned "success")
- `manage_keys.py revoke` → the same key that worked immediately started
  returning `401`
- The actual Flask HTTP server (not just an in-process test client) was
  started and hit with `curl` over a real socket connection

## Docker

```bash
docker build -t amosclaud-autonomous-server .
docker run -p 8001:8001 -v $(pwd)/keys.json:/app/keys.json amosclaud-autonomous-server
```

`keys.json` is mounted as a volume rather than baked into the image, so
keys survive container restarts and aren't shipped inside the image
itself.

## Limitations

- The planner is rule-based, not a large reasoning model — it's honest
  about that tradeoff (see "How planning actually works").
- `publish`'s exact payload shape is a best guess pending real API docs
  from amosclaud.com.
- Single-process Flask dev server — put gunicorn/waitress in front for
  production use.
- `keys.json` is a flat file — fine for a small number of admin-issued
  keys; move to a real datastore if you need many keys or multi-instance
  deployments sharing key state.
