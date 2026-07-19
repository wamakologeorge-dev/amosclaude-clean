import asyncio
import json
import struct

import pytest

from Amosclaud.api.path.byte.server.router.folder.cb.chapter.core.system.py import (
    build_tampered_data_system,
)
from Amosclaud.byte.core import ByteFrame
from Amosclaud.byte.doc.json.tools.card.cb import build_card
from Amosclaud.byte.py.ci.api.config.core.cb import TamperAPIConfigCoreCB
from Amosclaud.byte.py.ci.json.config.cb import CONFIG
from Amosclaud.byte.server import ByteClient


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_tampered_data_server_accepts_valid_and_quarantines_modified_frame(tmp_path):
    config = TamperAPIConfigCoreCB("127.0.0.1", 0, tmp_path / "evidence.jsonl", 2)
    server = await build_tampered_data_system(config).start()
    try:
        valid = await ByteClient("127.0.0.1", server.port).request(
            ByteFrame("security.ping", b"safe")
        )
        assert valid.json() == {"status": "protected"}

        envelope = json.loads(ByteFrame("security.ping", b"original").to_bytes())
        envelope["sha256"] = "0" * 64
        tampered = json.dumps(envelope, separators=(",", ":")).encode()
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        writer.write(struct.pack("!I", len(tampered)) + tampered)
        await writer.drain()
        size = struct.unpack("!I", await reader.readexactly(4))[0]
        rejection = ByteFrame.from_bytes(await reader.readexactly(size))
        writer.close()
        await writer.wait_closed()

        assert rejection.route == "security.tamper.rejected"
        assert rejection.json()["status"] == "rejected"
        assert server.status()["accepted"] == 1
        assert server.status()["quarantined"] == 1
        events = server.evidence_store.events()
        assert events[0]["failure"] == "ByteFrameError"
        evidence_text = config.evidence_path.read_text(encoding="utf-8")
        assert "original" not in evidence_text
        assert "payload" not in evidence_text
    finally:
        await server.close()


def test_requested_cb_paths_are_functional(tmp_path):
    card = build_card()
    assert card["stores_payloads"] is False
    assert "checksum-tamper-rejection" in CONFIG.tests
    server = build_tampered_data_system(
        TamperAPIConfigCoreCB("127.0.0.1", 0, tmp_path / "evidence.jsonl", 1)
    )
    assert server.status()["service"] == "amosclaud-tampered-data-server"
