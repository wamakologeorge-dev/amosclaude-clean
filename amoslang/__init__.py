"""Amosclaud Computer Language.

A small ownership-aware programming language with a real lexer, parser,
interpreter, command-line runner, and test suite.
"""

from .runtime import AmosError, Interpreter, run_source

__all__ = ["AmosError", "Interpreter", "run_source"]
__version__ = "0.1.0"
