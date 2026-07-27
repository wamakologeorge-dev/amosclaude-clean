from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from amoscloud_ai.local_cloud.crypto_identity import LocalNodeIdentity
from amoscloud_ai.local_cloud.p2p import LWWMap, PeerEnvelope, PeerProtocolError
from amoscloud_ai.local_cloud.plugins import (
    FolderPluginRegistry,
    PluginPackageError,
    PluginTrustStore,
    canonical_manifest_bytes,
    create_manifest,
)
from amoscloud_ai.local_cloud.sandbox import SandboxPolicy


def test_peer_envelope_is_signed_encrypted_and_trusted(tmp_path: Path) -> None:
    alice = LocalNodeIdentity(tmp_path / "alice")
    bob = LocalNodeIdentity(tmp_path / "bob")
    alice.initialize()
    bob.initialize()

    envelope = PeerEnvelope.create(
        identity=alice,
        recipient=bob.public_identity(),
        sequence=1,
        workspace_id="ws_" + "a" * 32,
        payload_type="crdt.snapshot",
        payload={"files": {"main.py": {"clock": 1}}},
    )

    assert "main.py" not in json.dumps(envelope.to_dict())
    payload = envelope.decrypt(
        recipient_identity=bob,
        trusted_sender_ids={alice.public_identity().node_id},
    )
    assert payload["files"]["main.py"]["clock"] == 1

    with pytest.raises(PeerProtocolError):
        envelope.decrypt(
            recipient_identity=bob,
            trusted_sender_ids=set(),
        )

    tampered = copy.deepcopy(envelope.to_dict())
    tampered["sequence"] = 2
    with pytest.raises(PeerProtocolError):
        PeerEnvelope.from_dict(tampered).decrypt(
            recipient_identity=bob,
            trusted_sender_ids={alice.public_identity().node_id},
        )


def test_lww_map_merge_is_commutative_and_tracks_deletes() -> None:
    left = LWWMap()
    right = LWWMap()
    left.set("app.py", "left", logical_clock=2, node_id="node_a")
    right.set("app.py", "right", logical_clock=2, node_id="node_b")
    right.set("readme", "hello", logical_clock=1, node_id="node_b")

    first = left.merge(right)
    second = right.merge(left)
    assert first.snapshot() == second.snapshot()
    assert first.materialize()["app.py"] == "right"

    deletion = LWWMap()
    deletion.delete("readme", logical_clock=3, node_id="node_a")
    assert "readme" not in first.merge(deletion).materialize()


def test_signed_folder_plugin_installs_only_after_trust(tmp_path: Path) -> None:
    publisher = LocalNodeIdentity(tmp_path / "publisher")
    publisher.initialize()
    package = tmp_path / "package"
    package.mkdir()
    (package / "plugin.py").write_text("def register():\n    return 'ok'\n")

    manifest = create_manifest(
        package_dir=package,
        name="example.guard",
        version="1.0.0",
        publisher=publisher.publisher_id(),
        entrypoint="plugin:register",
    )
    (package / "amosclaud-plugin.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (package / "amosclaud-plugin.sig").write_text(
        publisher.sign(canonical_manifest_bytes(manifest)) + "\n"
    )

    trust = PluginTrustStore()
    registry = FolderPluginRegistry(tmp_path / "installed", trust)
    with pytest.raises(PluginPackageError):
        registry.verify(package)

    trust.trust(
        publisher.publisher_id(),
        publisher.public_identity().signing_public_key,
    )
    installed = registry.install(package)
    assert Path(installed.install_path or "").joinpath("plugin.py").is_file()

    (package / "plugin.py").write_text("tampered = True\n")
    with pytest.raises(PluginPackageError):
        registry.verify(package)


def test_sandbox_command_has_no_host_privileges_or_vault_mount(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    command = SandboxPolicy().docker_command(
        workspace=workspace,
        image="python:3.12-slim",
        action="python_tests",
    )
    rendered = " ".join(command)
    assert "--network none" in rendered
    assert "--read-only" in command
    assert "--cap-drop ALL" in rendered
    assert "no-new-privileges" in command
    assert "/var/run/docker.sock" not in rendered
    assert "amosclaud_vault" not in rendered
    assert f"src={workspace.resolve()}" in rendered
    assert "readonly" in rendered
