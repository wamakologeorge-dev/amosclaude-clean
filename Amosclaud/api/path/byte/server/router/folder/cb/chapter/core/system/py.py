"""System factory at the requested deep Amosclaud API path."""

from __future__ import annotations

import asyncio

from Amosclaud.byte.py.ci.api.config.core.cb import TamperAPIConfigCoreCB
from Amosclaud.byte.router import ByteRouter
from Amosclaud.byte.system import ByteSystem
from Amosclaud.byte.tamper_server import TamperedDataServer, TamperEvidenceStore


def build_tampered_data_system(
    config: TamperAPIConfigCoreCB | None = None,
) -> TamperedDataServer:
    resolved = config or TamperAPIConfigCoreCB.from_env()
    router = ByteRouter()
    router.register("security.ping", lambda _frame: {"status": "protected"})
    router.register(
        "security.evidence.count",
        lambda _frame: {
            "events": len(TamperEvidenceStore(resolved.evidence_path).events(limit=1000))
        },
    )
    return TamperedDataServer(
        ByteSystem(router, name="amosclaud-tampered-data-system"),
        TamperEvidenceStore(resolved.evidence_path),
        host=resolved.host,
        port=resolved.port,
        request_timeout=resolved.request_timeout,
    )


def main() -> None:
    """Run the configured tampered-data server until interrupted."""
    server = build_tampered_data_system()
    try:
        asyncio.run(server.serve_forever())
    except KeyboardInterrupt:
        pass
