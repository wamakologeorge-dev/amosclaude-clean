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
    """Append a user message to an existing session and submit it to the agent.

    Loads the session, appends the user turn, calls
    :meth:`~amosclaud_agent_sdk.client.AmosclaudAgentClient.run` with the last
    12 messages as conversation context, appends the assistant reply, and
    persists the updated session — all in one call.

    Args:
        store: Session storage backend.
        client: HTTP client used to submit the request.
        session_id: ID of the session to continue.
        message: The user's next message.
        mode: Execution mode forwarded to :meth:`~AmosclaudAgentClient.run`.

    Returns:
        The raw API response dict from :meth:`~AmosclaudAgentClient.run`
        (not the final pipeline result — call
        :meth:`~AmosclaudAgentClient.pipeline` to poll completion).

    Raises:
        FileNotFoundError: If the session does not exist in ``store``.
    """
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
