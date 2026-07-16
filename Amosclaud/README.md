# Amosclaud Byte Tools

The `Amosclaud` namespace is the low-level developer library for integrity-checked messages,
local routing, TCP transport, and reproducible application bundles.

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

Run a real byte server:

```python
from Amosclaud.byte.server import ByteServer

server = await ByteServer(system, host="127.0.0.1", port=9050).start()
```

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
