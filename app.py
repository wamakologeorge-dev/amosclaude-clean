"""
Amosclaud Autonomous — an agent server that plans and executes multi-step
tasks using its own built-in model (no third-party API key needed) and can
publish results toward amosclaud.com.

Auth model:
  - The agent needs NO external API key (no OpenAI/Anthropic/etc. key) to
    run — it reasons using the local NGramModel from model.py, same as
    the base Amosclaud model server.
  - Callers of THIS server's own API must supply an admin-issued
    "Amosclaud key" via the X-Amosclaud-Key header. Only an admin with
    shell access can create these keys, via manage_keys.py — there is no
    self-serve signup or key-issuing endpoint.

Run:
    python manage_keys.py create "my first key"     # do this once, as admin
    python app.py

Config (environment variables):
    PORT                  port to listen on (default 8001)
    AMOSCLAUD_KEYS_PATH   path to the key store (default ./keys.json)
    AMOSCLAUD_SITE_URL    where publish() sends content (default https://amosclaud.com/api/publish)
    AMOSCLAUD_SITE_TOKEN  optional bearer token if the site itself requires auth
"""

import os
import time
import logging

from flask import Flask, request, jsonify, g

from model import NGramModel
from planner import auto_plan, run_plan, DEFAULT_MAX_STEPS, MAX_STEPS_HARD_CAP
from auth import verify_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("amosclaud-autonomous")

CORPUS_PATH = os.path.join(os.path.dirname(__file__), "corpus.txt")
PORT = int(os.environ.get("PORT", "8001"))
AGENT_NAME = "amosclaud-autonomous-v1"

app = Flask(__name__)
_model_state = {"model": None, "load_seconds": 0.0, "training_tokens": 0}


def load_model() -> NGramModel:
    start = time.time()
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    m = NGramModel()
    m.train(text)
    _model_state["model"] = m
    _model_state["load_seconds"] = time.time() - start
    _model_state["training_tokens"] = m.training_tokens
    logger.info(f"Agent model trained on {m.training_tokens} tokens in {_model_state['load_seconds']:.3f}s")
    return m


def get_model() -> NGramModel:
    if _model_state["model"] is None:
        load_model()
    return _model_state["model"]


# ---------------------------------------------------------------------------
# Auth: every route except /health requires a valid, non-revoked Amosclaud key
# ---------------------------------------------------------------------------

OPEN_PATHS = {"/health"}


@app.before_request
def require_amosclaud_key():
    if request.path in OPEN_PATHS:
        return None

    supplied = request.headers.get("X-Amosclaud-Key")
    key_id = verify_key(supplied)
    if key_id is None:
        return jsonify({
            "error": "missing or invalid Amosclaud key",
            "detail": "Send a valid key issued by an admin via manage_keys.py in the X-Amosclaud-Key header.",
        }), 401

    g.key_id = key_id
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    loaded = _model_state["model"] is not None
    return jsonify({
        "status": "ok" if loaded else "not_loaded",
        "agent": AGENT_NAME,
        "training_tokens": _model_state["training_tokens"],
        "belongs_to": "https://amosclaud.com",
    })


@app.route("/agent/run", methods=["POST"])
def agent_run():
    data = request.get_json(silent=True) or {}
    goal = data.get("goal")
    explicit_steps = data.get("steps")
    max_steps = data.get("max_steps", DEFAULT_MAX_STEPS)

    if not goal and not explicit_steps:
        return jsonify({"error": "provide either 'goal' (autonomous) or 'steps' (explicit plan)"}), 400

    if not isinstance(max_steps, int) or not (1 <= max_steps <= MAX_STEPS_HARD_CAP):
        return jsonify({"error": f"max_steps must be an integer between 1 and {MAX_STEPS_HARD_CAP}"}), 400

    if explicit_steps is not None:
        if not isinstance(explicit_steps, list) or not all(isinstance(s, dict) and "tool" in s for s in explicit_steps):
            return jsonify({"error": "'steps' must be a list of objects each containing at least a 'tool' field"}), 400
        plan = explicit_steps
        planning_mode = "explicit"
    else:
        plan = auto_plan(goal)
        planning_mode = "auto"

    model = get_model()
    result = run_plan(model, plan, max_steps=max_steps)

    return jsonify({
        "agent": AGENT_NAME,
        "requested_by_key": g.key_id,
        "goal": goal,
        "planning_mode": planning_mode,
        "plan": plan,
        **result,
    })


@app.route("/agent/tools", methods=["GET"])
def agent_tools():
    return jsonify({
        "tools": [
            {"name": "generate", "args": ["prompt", "max_new_tokens?", "temperature?", "top_p?"]},
            {"name": "fetch_url", "args": ["url"]},
            {"name": "publish", "args": ["title", "content"]},
        ]
    })


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    load_model()
    app.run(host="0.0.0.0", port=PORT)
