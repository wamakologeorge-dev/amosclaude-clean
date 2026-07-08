"""
Amosclaud-AI Chat API
REST endpoints for the Android and Web browser apps.
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

logger = logging.getLogger(__name__)

# In-memory conversation store (keyed by session_id)
_conversations: dict = {}


def create_app(static_folder: str = "web") -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, static_folder=static_folder, static_url_path="")
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # ------------------------------------------------------------------ health
    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "service": "amosclaud-ai", "version": "1.0.0"})

    # ------------------------------------------------------------------ static
    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # --------------------------------------------------------------- chat send
    @app.route("/api/chat", methods=["POST"])
    def chat():
        """
        POST /api/chat
        Body: { "message": "...", "session_id": "optional-uuid" }
        Returns: { "reply": "...", "session_id": "...", "timestamp": "..." }
        """
        data = request.get_json(silent=True) or {}
        message: str = (data.get("message") or "").strip()
        session_id: str = data.get("session_id") or _new_session_id()

        if not message:
            return jsonify({"error": "message is required"}), 400

        # Persist the user turn
        history = _conversations.setdefault(session_id, [])
        history.append({"role": "user", "content": message, "timestamp": _now()})

        # Generate a reply
        reply = _generate_reply(message, history)
        history.append({"role": "assistant", "content": reply, "timestamp": _now()})

        return jsonify({
            "reply": reply,
            "session_id": session_id,
            "timestamp": _now(),
        })

    # ------------------------------------------------------------ chat history
    @app.route("/api/chat/history/<session_id>", methods=["GET"])
    def chat_history(session_id: str):
        """Return conversation history for a session."""
        history = _conversations.get(session_id, [])
        return jsonify({"session_id": session_id, "history": history})

    # ---------------------------------------------------------- clear session
    @app.route("/api/chat/history/<session_id>", methods=["DELETE"])
    def clear_history(session_id: str):
        """Clear conversation history for a session."""
        _conversations.pop(session_id, None)
        return jsonify({"session_id": session_id, "cleared": True})

    # ---------------------------------------------------------- capabilities
    @app.route("/api/capabilities")
    def capabilities():
        """Return the AI capabilities exposed by this backend."""
        return jsonify({
            "name": "Amosclaud-AI",
            "version": "1.0.0",
            "capabilities": [
                "ci_cd_automation",
                "code_analysis",
                "deployment",
                "database_management",
                "git_operations",
                "intelligent_chat",
            ],
            "description": "Professional CI/CD & Deployment Automation AI",
        })

    
    # ------------------------------------------------------------------ CI
    _ci_runs = []

    @app.route("/ci")
    def ci_page():
        return send_from_directory(app.static_folder, "ci.html")

    @app.route("/ci/new")
    def ci_new_page():
        return send_from_directory(app.static_folder, "ci_new.html")

    @app.route("/api/ci/runs", methods=["GET"])
    def get_ci_runs():
        return jsonify(list(reversed(_ci_runs)))

    @app.route("/api/ci/trigger", methods=["POST"])
    def trigger_ci():
        data = request.get_json(silent=True) or {}
        env = data.get("environment", "production")
        
        import uuid
        run_id = str(uuid.uuid4())
        
        run_data = {
            "id": run_id,
            "status": "queued",
            "created_at": _now(),
            "environment": env,
            "logs": ""
        }
        _ci_runs.append(run_data)
        
        # Trigger GitHub Action
        import requests
        import os
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY", "wamakologeorge-dev/amosclaude-clean")
        
        if token and repo:
            url = f"https://api.github.com/repos/{repo}/dispatches"
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"token {token}"
            }
            payload = {
                "event_type": "deploy",
                "client_payload": {
                    "run_id": run_id,
                    "environment": env
                }
            }
            try:
                requests.post(url, json=payload, headers=headers)
            except Exception as e:
                logger.error(f"Failed to trigger GH action: {e}")
        
        return jsonify({"success": True, "run_id": run_id})

    @app.route("/api/ci/webhook", methods=["POST"])
    def ci_webhook():
        data = request.get_json(silent=True) or {}
        run_id = data.get("run_id")
        status = data.get("status")
        logs = data.get("logs")
        
        for run in _ci_runs:
            if run["id"] == run_id:
                if status:
                    run["status"] = status
                if logs:
                    run["logs"] += logs + "\n"
                break
        return jsonify({"success": True})


    return app


# ------------------------------------------------------------------ helpers

def _new_session_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_GREETINGS = {"hi", "hello", "hey", "greetings", "howdy"}

# Keyword → canned response mapping for the rule-based fallback
_KEYWORD_REPLIES: list[tuple[list[str], str]] = [
    (
        ["deploy", "deployment", "release"],
        "I can handle deployments for you! Use the CI/CD pipeline or tell me the target environment (dev / staging / production) and I'll kick off the deployment workflow.",
    ),
    (
        ["test", "tests", "testing", "pytest"],
        "I can run your test suite automatically. Trigger integration tests with `pytest tests/` or let me orchestrate the full CI pipeline including lint → test → build → deploy.",
    ),
    (
        ["database", "db", "migrate", "migration", "postgres"],
        "Database operations are fully automated: migrations, backups, and optimisation. Tell me which database action you need and I'll execute it safely.",
    ),
    (
        ["git", "commit", "branch", "push", "pull", "merge"],
        "I manage Git operations end-to-end: branching, committing, merging, and pushing. What repo action do you need?",
    ),
    (
        ["build", "compile", "docker", "container", "image"],
        "I can build Docker images, run `docker-compose up`, and manage the full container lifecycle. What would you like to build?",
    ),
    (
        ["code", "analyze", "review", "lint", "refactor"],
        "Code analysis is one of my core capabilities. I can review files, suggest refactors, run linters, and detect issues automatically.",
    ),
    (
        ["log", "logs", "error", "debug", "trace"],
        "I aggregate logs from all services in real-time. Share the error message or service name and I'll diagnose the issue.",
    ),
    (
        ["help", "what can you do", "capabilities", "features"],
        "I'm Amosclaud-AI — your autonomous CI/CD assistant! I can:\n• Deploy apps to any environment\n• Run automated tests\n• Manage databases\n• Analyse and edit code\n• Handle Git operations\n• Monitor logs and errors\n\nJust tell me what you need!",
    ),
    (
        ["browser", "search", "web", "url", "open"],
        "Use the built-in browser tab to navigate any URL. I can also help you search for documentation or resources — what are you looking for?",
    ),
]


def _rule_based_reply(message: str) -> str:
    """Keyword-driven fallback reply — no external API required."""
    lower = message.lower().strip(" ?!.,")

    if lower in _GREETINGS:
        return (
            "Hello! I'm Amosclaud-AI 🤖 — your intelligent CI/CD automation assistant. "
            "How can I help you today?"
        )

    for keywords, reply in _KEYWORD_REPLIES:
        if any(kw in lower for kw in keywords):
            return reply

    return (
        f"I received your message: \"{message}\"\n\n"
        "I'm Amosclaud-AI, specialising in CI/CD automation, deployments, code analysis, "
        "and DevOps workflows. Could you give me more details so I can assist you better?"
    )


def _generate_reply(message: str, history: list) -> str:
    """
    Generate a reply for the given message.
    Delegates to OpenAI when OPENAI_API_KEY is set; otherwise uses rule-based logic.
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        return _openai_reply(message, history, openai_key)
    return _rule_based_reply(message)


def _openai_reply(message: str, history: list, api_key: str) -> str:
    """Delegate to OpenAI Chat Completions API."""
    try:
        import openai  # type: ignore

        client = openai.OpenAI(api_key=api_key)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Amosclaud-AI, an intelligent CI/CD and DevOps automation assistant. "
                    "You help developers deploy apps, manage databases, run tests, analyse code, "
                    "and handle Git operations. Be concise, technical, and helpful."
                ),
            }
        ]
        for turn in history[:-1]:  # exclude the latest user message (already appended)
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": message})

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=512,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:  # pragma: no cover
        logger.warning("OpenAI call failed: %s — falling back to rule-based reply", exc)
        return _rule_based_reply(message)
