from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GeneratedAgentKey:
    key_id: str
    secret: str
    created_at: str


class AutonomousKeyStore:
    """Generate and verify Amosclaud-owned autonomous engineering keys.

    Raw keys are returned exactly once. Only a salted hash is persisted.
    These keys authenticate Amosclaud tasks; they are not OpenAI API keys.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        default = Path(os.getenv("AMOSCLAUD_AGENT_KEY_STORE", ".amosclaud/keys/autonomous.json"))
        self.path = Path(path) if path else default

    def generate(self, *, label: str = "autonomous-engineer") -> GeneratedAgentKey:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass

        key_id = secrets.token_hex(8)
        raw_secret = f"ak_{key_id}_{secrets.token_urlsafe(32)}"
        salt = secrets.token_hex(16)
        digest = hashlib.scrypt(
            raw_secret.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=2**14,
            r=8,
            p=1,
        ).hex()
        created_at = datetime.now(UTC).isoformat()
        payload = {
            "version": 1,
            "key_id": key_id,
            "label": label,
            "salt": salt,
            "digest": digest,
            "created_at": created_at,
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return GeneratedAgentKey(key_id=key_id, secret=raw_secret, created_at=created_at)

    def verify(self, candidate: str) -> bool:
        if not candidate or not self.path.exists():
            return False
        data = json.loads(self.path.read_text(encoding="utf-8"))
        calculated = hashlib.scrypt(
            candidate.encode("utf-8"),
            salt=bytes.fromhex(data["salt"]),
            n=2**14,
            r=8,
            p=1,
        ).hex()
        return hmac.compare_digest(calculated, data["digest"])
