import re

with open('src/amoscloud_ai/api/chat_api.py', 'r') as f:
    content = f.read()

new_routes = """
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
                    run["logs"] += logs + "\\n"
                break
        return jsonify({"success": True})

"""

content = content.replace('return app', new_routes + '\n    return app')

with open('src/amoscloud_ai/api/chat_api.py', 'w') as f:
    f.write(content)
