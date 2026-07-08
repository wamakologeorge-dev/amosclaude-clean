"""
Amosclaud-AI application entry point.
Starts the Flask API server that serves both the REST API and the web app.
"""
import os
import logging
from pathlib import Path

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

from src.amoscloud_ai.api import create_app  # noqa: E402

# Resolve the web/ directory relative to the project root
_HERE = Path(__file__).resolve().parent
_WEB_DIR = str(_HERE.parent.parent.parent / "web")

app = create_app(static_folder=_WEB_DIR)

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    import logging as _log
    _log.getLogger(__name__).info(
        "Starting Amosclaud-AI server on http://%s:%d (debug=%s)", host, port, debug
    )
    app.run(host=host, port=port, debug=debug)
