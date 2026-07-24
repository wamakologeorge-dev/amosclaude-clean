import json
import zipfile

import pytest

from Amosclaud.byte.core import ByteFrame, ByteFrameError
from Amosclaud.byte.router import ByteRouter, RouteNotFound
from Amosclaud.byte.server import ByteClient, ByteServer
from Amosclaud.byte.system import ByteSystem
from Amosclaud.byte.tools import chunk, compress, decompress, merge
from Amosclaud.lib.buddles import BundleBuilder as CompatibilityBundleBuilder
from Amosclaud.lib.bundles import BundleBuilder, BundleError, verify_bundle


def test_byte_frame_round_trip_and_tamper_detection():
    frame = ByteFrame.from_json("agent.task", {"objective": "verify bytes"})
    restored = ByteFrame.from_bytes(frame.to_bytes())
    assert restored.json() == {"objective": "verify bytes"}
    envelope = json.loads(frame.to_bytes())
    envelope["sha256"] = "0" * 64
    with pytest.raises(ByteFrameError, match="checksum"):
        ByteFrame.from_bytes(json.dumps(envelope).encode())


def test_router_system_executes_real_sync_and_async_routes():
    router = ByteRouter()
    router.register("bytes.reverse", lambda frame: frame.payload[::-1])

    @router.route("bytes.count")
    async def count(frame):
        return {"bytes": len(frame.payload)}

    system = ByteSystem(router)
    system.start()
    assert system.execute_sync(ByteFrame("bytes.reverse", b"abc")).payload == b"cba"
    assert system.execute_sync(ByteFrame("bytes.count", b"four")).json() == {"bytes": 4}
    assert system.status()["requests"] == 2
    with pytest.raises(RouteNotFound):
        system.execute_sync(ByteFrame("missing", b""))


def test_byte_tools_chunk_compress_and_verify_merge():
    data = (b"amosclaud-byte-system" * 1000) + b"done"
    compressed = compress(data)
    assert decompress(compressed) == data
    parts = chunk(data, 777)
    assert merge(parts, expected_sha256=ByteFrame("data", data).sha256) == data


@pytest.mark.anyio
async def test_byte_server_routes_frame_over_real_tcp():
    router = ByteRouter()
    router.register("echo", lambda frame: frame.payload)
    server = await ByteServer(ByteSystem(router)).start()
    try:
        response = await ByteClient("127.0.0.1", server.port).request(ByteFrame("echo", b"live"))
        assert response.payload == b"live"
        assert response.headers["request-id"]
    finally:
        await server.close()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_bundle_library_is_deterministic_and_compatibility_alias_works(tmp_path):
    source = tmp_path / "app"
    source.mkdir()
    (source / "main.py").write_text("print('Amosclaud')\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=excluded", encoding="utf-8")
    first = BundleBuilder(source).build(tmp_path / "one.zip", metadata={"version": "1.0.0"})
    second = CompatibilityBundleBuilder(source).build(
        tmp_path / "two.zip", metadata={"version": "1.0.0"}
    )
    assert first.path.read_bytes() == second.path.read_bytes()
    assert verify_bundle(first.path) == {
        "valid": True,
        "files": 1,
        "metadata": {"version": "1.0.0"},
    }
    with zipfile.ZipFile(first.path) as archive:
        assert ".env" not in archive.namelist()


def test_bundle_verification_rejects_tampered_archive(tmp_path):
    source = tmp_path / "app"
    source.mkdir()
    (source / "data.txt").write_text("original", encoding="utf-8")
    bundle = BundleBuilder(source).build(tmp_path / "app.zip")
    with zipfile.ZipFile(bundle.path) as archive:
        manifest = archive.read("AMOSCLAUD_BUNDLE_MANIFEST.json")
    with zipfile.ZipFile(bundle.path, "w") as archive:
        archive.writestr("data.txt", "tampered")
        archive.writestr("AMOSCLAUD_BUNDLE_MANIFEST.json", manifest)
    with pytest.raises(BundleError, match="mismatch"):
        verify_bundle(bundle.path)
