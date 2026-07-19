"""Bidirectional multi-turn client built on durable Amosclaud sessions."""
from __future__ import annotations

import dataclasses
from collections.abc import AsyncGenerator, AsyncIterator

from .client import AmosclaudAgentClient
from .options import AmosclaudAgentOptions
from .query import QueryMessage, query
from .session_store import SessionStore
from .sessions import AgentSession, _CONVERSATION_WINDOW, create_session, save_session


class AmosclaudSDKClient:
    def __init__(
        self,
        options: AmosclaudAgentOptions | None = None,
        *,
        client: AmosclaudAgentClient | None = None,
        store: SessionStore | None = None,
    ) -> None:
        self.options = options or AmosclaudAgentOptions()
        self.client = client or AmosclaudAgentClient()
        self.store = store or SessionStore()
        self.session: AgentSession | None = None
        self._pending: list[QueryMessage] = []

    async def __aenter__(self) -> "AmosclaudSDKClient":
        self.session = create_session(self.store, metadata={"source": "sdk-client"})
        return self

    async def __aexit__(self, *_args) -> None:
        if self.session:
            save_session(self.store, self.session)

    async def send(self, prompt: str) -> None:
        if self.session is None:
            raise RuntimeError("use AmosclaudSDKClient as an async context manager")
        self.session.append("user", prompt)
        conversation_metadata = {
            **self.options.metadata,
            "conversation_id": self.session.id,
            "conversation": [item.to_dict() for item in self.session.messages[-_CONVERSATION_WINDOW:]],
        }
        query_options = dataclasses.replace(self.options, metadata=conversation_metadata)
        self._pending = [message async for message in query(prompt, options=query_options, client=self.client)]
        assistant = next((item for item in self._pending if item.type == "assistant"), None)
        if assistant:
            self.session.append("assistant", assistant.content)
        save_session(self.store, self.session)

    async def receive(self) -> AsyncGenerator[QueryMessage, None]:
        while self._pending:
            yield self._pending.pop(0)
