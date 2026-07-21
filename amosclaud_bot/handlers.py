"""Built-in command handlers for AmosclaudBot."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bot import AmosclaudBot


def handle_ping(_args: str, _bot: "AmosclaudBot") -> str:
    """Respond to ``!ping`` with a liveness confirmation."""
    return "pong"


def handle_info(_args: str, bot: "AmosclaudBot") -> str:
    """Respond to ``!info`` with the bot's current state summary."""
    state = bot.info()
    lines = [
        f"session: {state['session_id']}",
        f"commands: {', '.join(state['registered_commands']) or '(none)'}",
    ]
    if state["system_prompt"]:
        lines.append(f"system_prompt: {state['system_prompt']}")
    return "\n".join(lines)


def handle_help(_args: str, bot: "AmosclaudBot") -> str:
    """Respond to ``!help`` with a list of available commands."""
    commands = bot.info()["registered_commands"]
    if not commands:
        return "No commands registered."
    formatted = "\n".join(f"  !{name}" for name in commands)
    return f"Available commands:\n{formatted}"
