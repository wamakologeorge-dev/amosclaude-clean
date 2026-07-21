"""Core AmosclaudBot class with command routing and agent fallback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from amosclaud_agent_sdk.client import AmosclaudAgentClient
from amosclaud_agent_sdk.errors import AmosclaudSDKError
from amosclaud_agent_sdk.options import AmosclaudAgentOptions
from amosclaud_agent_sdk.session_store import SessionStore
from amosclaud_agent_sdk.sessions import AgentSession, create_session, save_session

from .errors import BotError, UnknownCommandError

BotHandler = Callable[[str, "AmosclaudBot"], str]

_COMMAND_PREFIX = "!"


@dataclass
class AmosclaudBot:
    """Command-routing bot backed by the Amosclaud Agent SDK.

    Commands are strings that begin with ``!`` (e.g. ``!ping``).  Natural-language
    messages are forwarded to the Amosclaud agent and the reply is returned.

    Usage::

        bot = AmosclaudBot(api_key="amos_aut_…")
        bot.register("ping", lambda _msg, _bot: "pong")
        reply = bot.dispatch("!ping")

    Args:
        api_key: Bearer token for the Amosclaud API. Falls back to the
            ``AMOSCLAUD_API_KEY`` environment variable when omitted.
        session_cookie: Web-session cookie, alternative to ``api_key``.
        system_prompt: Instruction prepended to every agent query.
        store_path: Directory used to persist sessions.  Defaults to
            ``.amosclaud/sessions``.
    """

    api_key: str | None = None
    session_cookie: str | None = None
    system_prompt: str | None = None
    store_path: str = ".amosclaud/sessions"

    _handlers: dict[str, BotHandler] = field(default_factory=dict, init=False, repr=False)
    _client: AmosclaudAgentClient | None = field(default=None, init=False, repr=False)
    _store: SessionStore | None = field(default=None, init=False, repr=False)
    _session: AgentSession | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = AmosclaudAgentClient(
            api_key=self.api_key,
            session_cookie=self.session_cookie,
        )
        self._store = SessionStore(self.store_path)
        self._session = create_session(self._store, metadata={"source": "amosclaud-bot"})
        self._register_builtins()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, command: str, handler: BotHandler) -> None:
        """Register a handler for ``!<command>`` messages.

        Args:
            command: Name without the ``!`` prefix (e.g. ``"ping"``).
            handler: Callable that receives the raw message text and this bot
                instance, and returns a reply string.

        Raises:
            ValueError: If ``command`` is blank or already registered.
        """
        name = command.strip().lstrip(_COMMAND_PREFIX)
        if not name:
            raise ValueError("command name is required")
        if name in self._handlers:
            raise ValueError(f"command already registered: {name}")
        self._handlers[name] = handler

    def dispatch(self, message: str) -> str:
        """Route ``message`` to a command handler or the agent.

        If the message starts with ``!`` the remainder is used as the command
        name.  Unknown commands raise :exc:`UnknownCommandError`.  All other
        text is forwarded to the Amosclaud agent via the SDK.

        Args:
            message: Raw input text.

        Returns:
            The reply string from the handler or the agent.

        Raises:
            UnknownCommandError: If the ``!command`` name has no handler.
            BotError: On agent communication failure.
        """
        text = message.strip()
        if text.startswith(_COMMAND_PREFIX):
            return self._handle_command(text[len(_COMMAND_PREFIX):])
        return self._query_agent(text)

    def info(self) -> dict[str, Any]:
        """Return a summary of the bot's current state."""
        return {
            "session_id": self._session.id if self._session else None,
            "registered_commands": sorted(self._handlers),
            "system_prompt": self.system_prompt,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_command(self, raw: str) -> str:
        parts = raw.strip().split(maxsplit=1)
        name = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        handler = self._handlers.get(name)
        if handler is None:
            raise UnknownCommandError(f"unknown command: {name!r}")
        return handler(args, self)

    def _query_agent(self, prompt: str) -> str:
        if not prompt:
            raise BotError("message is empty")
        options = AmosclaudAgentOptions(system_prompt=self.system_prompt)
        try:
            result = self._client.run_and_wait(prompt, mode="build", metadata={"source": "amosclaud-bot"})
        except AmosclaudSDKError as exc:
            raise BotError(str(exc)) from exc
        reply = str(result.get("reply") or result.get("message") or "Task completed")
        if self._session is not None:
            self._session.append("user", prompt)
            self._session.append("assistant", reply)
            save_session(self._store, self._session)
        return reply

    def _register_builtins(self) -> None:
        from .handlers import handle_help, handle_info, handle_ping

        self._handlers["ping"] = handle_ping
        self._handlers["info"] = handle_info
        self._handlers["help"] = handle_help
