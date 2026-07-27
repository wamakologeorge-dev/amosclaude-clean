# Amosclaud Decentralized Node Foundation

This revision adds the first implementation boundary for four long-term platform
capabilities. It is deliberately conservative: peers and plugins are never trusted
automatically, signed packages are not executed during installation, and sandbox
profiles do not receive the Docker socket or the local secrets vault.

## 1. Peer-to-peer synchronization protocol

`amoscloud_ai/local_cloud/p2p.py` provides:

- Ed25519-signed peer envelopes;
- X25519 ephemeral key exchange with ChaCha20-Poly1305 payload encryption;
- explicit local peer trust by node ID;
- sequence numbers for replay tracking by the caller;
- a deterministic last-writer-wins map CRDT for mergeable metadata.

The protocol module defines secure messages and merge behavior. It does not yet
open network listeners, discover peers, or synchronize complete Git repositories.
A later transport can carry the same envelopes over LAN, QUIC, WebRTC, removable
media, or an operator-controlled relay without changing the signed payload format.

A node must keep a durable highest-seen sequence per trusted peer and workspace.
Messages with an older or repeated sequence must be rejected by the transport layer.

## 2. Signed folder plugin packages

`amoscloud_ai/local_cloud/plugins.py` provides a decentralized package format:

```text
plugin-folder/
├── amosclaud-plugin.json
├── amosclaud-plugin.sig
└── package files declared by hash
```

The manifest names every regular payload file and its SHA-256 digest. The complete
canonical manifest is signed with the publisher's Ed25519 key. Installation works
only after that publisher key is added to the node's local trust store.

Installation copies verified files into a dedicated extension directory. Plugins
must not be installed in `amosclaud_vault/`; that directory is reserved for secrets.
Installation does not import, activate, or execute plugin code.

## 3. Hardened sandbox profile

`amoscloud_ai/local_cloud/sandbox.py` generates fixed Docker argument arrays for
supported verification actions. The baseline profile uses:

- no network by default;
- a read-only container root filesystem;
- a read-only workspace bind mount;
- all Linux capabilities dropped;
- `no-new-privileges`;
- non-root UID/GID;
- PID, memory, and CPU limits;
- a bounded temporary filesystem;
- no Docker socket;
- no vault mount;
- no caller-provided shell command.

This is a hardened baseline, not a claim of perfect isolation. Higher-risk workloads
should use rootless containers, gVisor/Kata Containers, Firecracker, or a WebAssembly
runtime according to host capabilities.

## 4. Cross-platform headless supervisor

`daemon/main.go` implements `amosclaudd`, a small Go supervisor that starts the
existing FastAPI local node, waits for `/live`, forwards shutdown, and reports child
failure. It has no dependency on Google, GitHub, Railway, or another hosted identity.

Build it from the repository root:

```bash
cd daemon
go build -o amosclaudd .
```

Windows:

```powershell
cd daemon
go build -o amosclaudd.exe .
.\amosclaudd.exe -root ..
```

Linux/macOS:

```bash
./amosclaudd -root ..
```

The first version is a foreground supervisor suitable for systemd, launchd, Windows
Task Scheduler, NSSM, or another operator-controlled service wrapper. Native service
registration can be added later without putting that platform-specific privilege
inside the Python API.

## Trust boundary

- Pairing a peer and trusting a publisher are explicit local actions.
- Signed data is still validated before use.
- CRDT merges do not directly overwrite workspace files.
- Plugin installation and plugin activation are separate operations.
- Untrusted code executes only through a fixed sandbox action catalog.
- Secrets remain outside peer snapshots, plugin packages, and sandbox mounts.
