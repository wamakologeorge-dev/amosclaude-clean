from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "services.template_studio.app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8090")),
        reload=False,
    )
