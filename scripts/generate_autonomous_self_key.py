"""Generate a strong private key for Amosclaud Autonomous internal control traffic."""
from __future__ import annotations

import secrets


if __name__ == "__main__":
    print("autonomous_" + secrets.token_urlsafe(48))
