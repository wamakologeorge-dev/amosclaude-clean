with open('src/amoscloud_ai/api/chat_api.py', 'r') as f:
    content = f.read()

# Fix imports
content = content.replace("import os\nimport json", "import os\nimport json\nimport uuid\nimport requests")

# Fix _ci_runs
import re

new_trigger = """
    @app.route("/api/ci/trigger", methods=["POST"])
    def trigger_ci():
        data = request.get_json(silent=True) or {}
        env = data.get("environment", "production")
        
        run_id = str(uuid.uuid4())
        
        run_data = {
            "id": run_id,
            "status": "queued",
            "created_at": _now(),
            "environment": env,
            "logs": ""
        }
        _ci_runs.append(run_data)
        if len(_ci_runs) > 100:
            _ci_runs.pop(0)
        
        # Trigger GitHub Action
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
                    "environment": env,
                    "webhook_secret": os.environ.get("WEBHOOK_SECRET", "default_secret")
                }
            }
            try:
                requests.post(url, json=payload, headers=headers, timeout=10)
            except Exception as e:
                logger.error(f"Failed to trigger GH action: URL={url}, Error={e}")
        
        return jsonify({"success": True, "run_id": run_id})
"""

# Replace trigger_ci
start_trigger = content.find('@app.route("/api/ci/trigger", methods=["POST"])')
end_trigger = content.find('@app.route("/api/ci/webhook", methods=["POST"])')
content = content[:start_trigger] + new_trigger.strip() + '\n\n    ' + content[end_trigger:]

new_webhook = """
    @app.route("/api/ci/webhook", methods=["POST"])
    def ci_webhook():
        data = request.get_json(silent=True) or {}
        secret = data.get("webhook_secret")
        if os.environ.get("WEBHOOK_SECRET") and secret != os.environ.get("WEBHOOK_SECRET"):
            return jsonify({"error": "Unauthorized"}), 401
            
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
"""

start_webhook = content.find('@app.route("/api/ci/webhook", methods=["POST"])')
end_webhook = content.find('return app', start_webhook)
content = content[:start_webhook] + new_webhook.strip() + '\n\n    ' + content[end_webhook:]

with open('src/amoscloud_ai/api/chat_api.py', 'w') as f:
    f.write(content)
