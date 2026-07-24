import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "sdk-python"))
from amosclaud_client import AmosclaudClient  # noqa: E402

client = AmosclaudClient(os.environ["AMOSCLAUD_API_KEY"])
task = client.create_task(
    "Review this repository and return verification evidence",
    mode="review",
    delivery="report",
    execution_target="cloud",
)
print(task)
