"""Standalone FastAPI entry point for the futuristic Autonomous architecture."""

from fastapi import FastAPI

from .router import router

app = FastAPI(title="Amosclaud Futuristic Autonomous Agent", version="2.0.0")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "amosclaud-futuristic-autonomous"}
