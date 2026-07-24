"""Amosclaud Computer Language runtime package."""

from .runtime import AmclError, Interpreter, run_source

__all__ = ["AmclError", "Interpreter", "run_source"]
__version__ = "0.1.0"
