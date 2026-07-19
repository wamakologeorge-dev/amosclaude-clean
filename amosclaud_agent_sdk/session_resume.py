"""Resume a durable session and continue it through Amosclaud Autonomous."""
from __future__ import annotations

from typing import Any

from .client import AmosclaudAgentClient
from .session_store import SessionStore
from .sessions import _CONVERSATION_WINDOW, load_session, save_session


def continue_session(
    store: SessionStore,
    client: AmosclaudAgentClient,
    session_id: str,
    message: str,
    *,
    mode: str = "build",
) -> dict[str, Any]:
    session = load_session(store, session_id)
    session.append("user", message)
    response = client.run(
        message,
        mode=mode,
        metadata={
            "conversation_id": session.id,
            "conversation": [item.to_dict() for item in session.messages[-_CONVERSATION_WINDOW:]],
        },
    )
    reply = str(response.get("reply") or response.get("message") or "Request accepted")
    session.append(
        "assistant",
        reply,
        {"pipeline_id": response.get("pipeline_id"), "status": response.get("status")},
    )
    save_session(store, session)
    return response
