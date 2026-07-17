"""
auth.py — admin-issued API key management for the Amosclaud Autonomous
server.

Design:
  - There is no external "bring your own API key" requirement. The agent
    runs entirely on its own built-in model (model.py / NGramModel) and
    needs no third-party LLM credentials.
  - Instead, ADMIN-issued "Amosclaud keys" gate access to the agent's own
    HTTP API. Only an admin (someone with shell access to this machine)
    can create or revoke keys, using manage_keys.py.
  - Keys are never stored in plaintext. Each key is a random token; what
    gets written to keys.json is a salted SHA-256 hash plus metadata
    (label, created_at). The plaintext key is shown exactly once, at
    creation time, and cannot be recovered afterward — same model as
    GitHub personal access tokens, AWS secret keys, etc.
"""

import hashlib
import json
import os
import secrets
import time
from typing import Optional, Dict, List

KEYS_PATH = os.environ.get(
    "AMOSCLAUD_KEYS_PATH", os.path.join(os.path.dirname(__file__), "keys.json")
)
KEY_PREFIX = "amcl_"  # "Amosclaud" — makes issued keys recognizable at a glance


def _load_store() -> Dict:
    if not os.path.exists(KEYS_PATH):
        return {"keys": []}
    with open(KEYS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_store(store: Dict) -> None:
    tmp_path = KEYS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
    os.replace(tmp_path, KEYS_PATH)  # atomic on POSIX


def _hash_key(plaintext_key: str, salt: str) -> str:
    return hashlib.sha256((salt + plaintext_key).encode("utf-8")).hexdigest()


def create_key(label: str) -> str:
    """Admin-only: generates a new plaintext key, stores only its hash, and
    returns the plaintext key (the only time it will ever be visible)."""
    plaintext_key = KEY_PREFIX + secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    key_hash = _hash_key(plaintext_key, salt)

    store = _load_store()
    store["keys"].append({
        "id": secrets.token_hex(6),
        "label": label,
        "salt": salt,
        "hash": key_hash,
        "created_at": int(time.time()),
        "revoked": False,
    })
    _save_store(store)
    return plaintext_key


def revoke_key(key_id: str) -> bool:
    store = _load_store()
    found = False
    for entry in store["keys"]:
        if entry["id"] == key_id:
            entry["revoked"] = True
            found = True
    if found:
        _save_store(store)
    return found


def list_keys() -> List[Dict]:
    """Returns metadata only — never plaintext keys or hashes to callers
    outside this module."""
    store = _load_store()
    return [
        {
            "id": e["id"],
            "label": e["label"],
            "created_at": e["created_at"],
            "revoked": e["revoked"],
        }
        for e in store["keys"]
    ]


def verify_key(plaintext_key: Optional[str]) -> Optional[str]:
    """Returns the key's id if valid and not revoked, else None."""
    if not plaintext_key:
        return None
    store = _load_store()
    for entry in store["keys"]:
        if entry["revoked"]:
            continue
        if _hash_key(plaintext_key, entry["salt"]) == entry["hash"]:
            return entry["id"]
    return None
