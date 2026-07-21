"""Stable exception hierarchy for amosclaud_bot."""


class BotError(RuntimeError):
    """Base error for the Amosclaud Bot."""


class UnknownCommandError(BotError):
    """A command prefix was recognised but no handler is registered for it."""
