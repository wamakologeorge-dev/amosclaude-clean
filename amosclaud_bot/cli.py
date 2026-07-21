"""Command-line entry point for AmosclaudBot."""

from __future__ import annotations

import argparse
import os
import sys

from .bot import AmosclaudBot
from .errors import BotError, UnknownCommandError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="amosclaud-bot",
        description="Amosclaud Bot — dispatch commands and agent queries from the terminal.",
    )
    parser.add_argument("message", nargs="?", help="Message to dispatch (omit for interactive mode).")
    parser.add_argument("--api-key", default=None, help="Amosclaud API key (overrides AMOSCLAUD_API_KEY).")
    parser.add_argument("--system-prompt", default=None, help="System instruction for agent queries.")
    parser.add_argument("--store-path", default=".amosclaud/sessions", help="Session store directory.")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    bot = AmosclaudBot(
        api_key=args.api_key or os.getenv("AMOSCLAUD_API_KEY"),
        system_prompt=args.system_prompt,
        store_path=args.store_path,
    )

    if args.message:
        _dispatch_once(bot, args.message)
    else:
        _interactive(bot)


def _dispatch_once(bot: AmosclaudBot, message: str) -> None:
    try:
        reply = bot.dispatch(message)
        print(reply)
    except UnknownCommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except BotError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


def _interactive(bot: AmosclaudBot) -> None:
    print("Amosclaud Bot — interactive mode. Type !help for commands, Ctrl-C to exit.")
    while True:
        try:
            line = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not line:
            continue
        try:
            reply = bot.dispatch(line)
            print(reply)
        except UnknownCommandError as exc:
            print(f"error: {exc}", file=sys.stderr)
        except BotError as exc:
            print(f"error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
