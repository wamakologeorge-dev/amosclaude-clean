#!/usr/bin/env python3
"""Generate a cryptographically secure Amosclaud cloud-agent API key.

The generated secret is intended for the Railway variable AMOSCLAUD_API_KEY.
It is printed once and must never be committed to the repository.
"""

from __future__ import annotations

import secrets


def generate_key() -> str:
    """Return a high-entropy, URL-safe Amosclaud API key."""
    return f"amos_{secrets.token_urlsafe(48)}"


if __name__ == "__main__":
    print(generate_key())
