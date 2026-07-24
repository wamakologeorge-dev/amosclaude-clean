# Amosclaud Python SDK

```python
from amosclaud_client import AmosclaudClient

client = AmosclaudClient("amos_live_your_key")
task = client.create_task(
    "Fix the failing tests and prepare a pull request",
    repository="owner/project",
    execution_target="github",
    require_approval=True,
)
print(task["id"])
```

The SDK uses only Python's standard library. Customer keys are sent as Bearer credentials and are never written to disk.
