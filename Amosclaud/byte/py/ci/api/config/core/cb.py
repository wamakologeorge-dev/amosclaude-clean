"""Runtime API policy for the Amosclaud tampered-data server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TamperAPIConfigCoreCB:
    host: str
    port: int
    evidence_path: Path
    request_timeout: float

    @classmethod
    def from_env(cls) -> "TamperAPIConfigCoreCB":
        port = int(os.getenv("AMOSCLAUD_TAMPER_PORT", "9060"))
        timeout = float(os.getenv("AMOSCLAUD_TAMPER_TIMEOUT", "30"))
        if not 0 <= port <= 65535:
            raise ValueError("AMOSCLAUD_TAMPER_PORT must be between 0 and 65535")
        if not 0.1 <= timeout <= 300:
            raise ValueError("AMOSCLAUD_TAMPER_TIMEOUT must be between 0.1 and 300 seconds")
        evidence = Path(
            os.getenv("AMOSCLAUD_TAMPER_EVIDENCE", "data/security/tamper-evidence.jsonl")
        ).expanduser()
        return cls(
            host=os.getenv("AMOSCLAUD_TAMPER_HOST", "127.0.0.1").strip(),
            port=port,
            evidence_path=evidence,
            request_timeout=timeout,
        )
