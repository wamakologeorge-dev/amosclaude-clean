"""JSON documentation card for the tampered-data server."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TamperedDataCardCB:
    name: str = "Amosclaud Tampered Data Server"
    import_path: str = "Amosclaud.byte.doc.json.tools.card.cb"
    protocol: str = "amosclaud-byte-frame-v1"
    purpose: str = "Reject altered byte frames and retain evidence-only quarantine records."
    stores_payloads: bool = False
    capabilities: tuple[str, ...] = (
        "sha256-integrity",
        "length-validation",
        "evidence-quarantine",
        "safe-route-dispatch",
    )

    def json_card(self) -> dict[str, Any]:
        return asdict(self)


def build_card() -> dict[str, Any]:
    return TamperedDataCardCB().json_card()
