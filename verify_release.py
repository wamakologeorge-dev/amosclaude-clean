"""Self-test for the portable Amosclaud Quick release."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from amoscloud_ai.developer_fastpath import quickcheck, validate_repository


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="amosclaud-quick-") as directory:
        root = Path(directory)
        (root / "app.py").write_text("def health():\n    return True\n", encoding="utf-8")
        (root / "config.json").write_text('{"ready": true}\n', encoding="utf-8")
        (root / ".env").write_text("SECRET=must-not-be-read\n", encoding="utf-8")

        report = quickcheck(root, "Verify service health", max_lines=12, max_files=3)
        assert report["status"] == "passed", report
        assert ".env" in report["context"]["sensitive_files_skipped"], report
        assert "must-not-be-read" not in json.dumps(report), report

        broken = root / "broken.py"
        broken.write_text("def broken(:\n    pass\n", encoding="utf-8")
        failure = validate_repository(root)
        assert failure["passed"] is False, failure
        assert any(item["path"] == "broken.py" for item in failure["failures"]), failure

    print("Amosclaud Quick v1.0.0 release verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
