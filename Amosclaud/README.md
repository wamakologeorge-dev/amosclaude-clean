# Amosclaud Byte Tools

The `Amosclaud` namespace is the low-level developer library for integrity-checked messages,
local routing, TCP transport, reproducible application bundles, and the internal platform command bus.

```python
from Amosclaud.byte.core import ByteFrame
from Amosclaud.byte.router import ByteRouter
from Amosclaud.byte.system import ByteSystem

router = ByteRouter()
router.register("code.count", lambda frame: {"bytes": len(frame.payload)})

system = ByteSystem(router)
system.start()
result = system.execute_sync(ByteFrame.from_text("code.count", "build safely"))
print(result.json())
```

## Connected platform bus

`Amosclaud.platform_bus.PlatformByteBus` connects the Byte runtime to the shared
`database/` state used by the API gateway, Autonomous Agent, root orchestrator,
repository platform, fixer, and CI workers.

```python
from Amosclaud.platform_bus import PlatformByteBus

bus = PlatformByteBus(b"replace-with-a-secret-from-the-environment")
status = bus.execute(
    bus.frame("platform.job.status", {"task_id": "repair-123"})
).json()
```

Available controlled routes are:

- `platform.health`
- `platform.repository.summary`
- `platform.job.status`
- `platform.job.transition`

Frames are authenticated with HMAC-SHA256, expire after a short TTL, and include
a one-time nonce. Replayed, altered, unsigned, or expired frames are rejected.
A job cannot transition to `passed` without a verification ID, and the linked
`CIPipeline` is updated in the same database transaction.

The public API must not expose the byte-bus secret. Configure it only on trusted
platform services:

```bash
export AMOSCLAUD_BYTE_BUS_SECRET="a-random-secret-with-at-least-32-characters"
export AMOSCLAUD_PLATFORM_DATABASE_URL="sqlite:///./data/amosclaud-platform.db"
```

The API gateway remains the authenticated public boundary. The byte bus is an
internal command and state-coordination layer, not a replacement for user login,
repository authorization, or public HTTPS.

## TCP transport

Run a real byte server:

```python
from Amosclaud.byte.server import ByteServer

server = await ByteServer(system, host="127.0.0.1", port=9050).start()
```

The TCP server should remain on localhost or a protected private network until
mutual TLS and service identity are configured. Payload checksums detect changes,
but checksums alone do not authenticate a remote client.

## Verified bundles

Build and verify a portable bundle:

```python
from pathlib import Path
from Amosclaud.lib.bundles import BundleBuilder, verify_bundle

bundle = BundleBuilder(Path("my-app")).build(
    Path("dist/my-app.zip"),
    metadata={"version": "1.0.0"},
)
assert verify_bundle(bundle.path)["valid"]
```

`Amosclaud.lib.buddles` remains available as a compatibility import for the originally requested
name. New integrations should use `Amosclaud.lib.bundles`.

Run the evidence-only tamper detection server with:

```bash
export AMOSCLAUD_TAMPER_HOST=127.0.0.1
export AMOSCLAUD_TAMPER_PORT=9060
export AMOSCLAUD_TAMPER_EVIDENCE=data/security/tamper-evidence.jsonl
amosclaud-tamper-server
```

Its JSON card is available from `Amosclaud.byte.doc.json.tools.card.cb`; CI and runtime policies
are exposed through the requested `Amosclaud.byte.py.ci...cb` module paths.

Create and install a managed Y bundle with a CB receipt:

```python
from pathlib import Path
from Amosclaud.y.bundle.system.cb import YBundleSystemCB

system = YBundleSystemCB(Path("data/y-bundles"))
record = system.build(
    Path("my-app"),
    name="my-app",
    version="1.0.0",
)
assert system.verify(record.bundle_id)["valid"]
installed_folder = system.install(record.bundle_id)
```

The Y bundle system maintains an atomic index, archive checksum, CB receipt checksum, embedded
per-file manifest, and safe extraction limits. It rejects altered archives, altered receipts,
absolute paths, `..` traversal, symlinks, oversized output, and excessive file counts.
