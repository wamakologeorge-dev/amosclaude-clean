"""Amosclaud public API contract package.

This package intentionally owns shared request/response schemas.  The unrelated
root ``app.py`` dashboard remains a standalone executable module; declaring this
directory as a package prevents ``import app.models`` from executing that
application and its filesystem side effects during test collection.
"""

__all__: list[str] = []
