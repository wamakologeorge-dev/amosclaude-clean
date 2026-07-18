"""CI JSON configuration for tamper-server validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TamperCIJSONConfigCB:
    schema_version: str = "1.0.0"
    import_path: str = "Amosclaud.byte.py.ci.json.config.cb"
    tests: tuple[str, ...] = (
        "valid-frame-round-trip",
        "checksum-tamper-rejection",
        "evidence-does-not-store-payload",
        "wire-size-limit",
    )
    fail_on_tamper_acceptance: bool = True

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


CONFIG = TamperCIJSONConfigCB()
