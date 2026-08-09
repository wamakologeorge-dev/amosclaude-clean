from __future__ import annotations

import importlib.util
import json
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "ai_patch_executor.py"


def load_module():
    spec = importlib.util.spec_from_file_location("ai_patch_executor", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    status = 200

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def run(command: list[str], cwd: Path) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout


def initialize_repository(path: Path) -> None:
    (path / "src").mkdir(parents=True)
    (path / "tests").mkdir()
    (path / "src" / "worker.py").write_text("def work():\n    return 1\n", encoding="utf-8")
    (path / "tests" / "test_worker.py").write_text(
        "from src.worker import work\n\ndef test_work():\n    assert work() == 1\n",
        encoding="utf-8",
    )
    (path / ".env").write_text("API_KEY=not-for-model-context\n", encoding="utf-8")
    (path / "id_rsa").write_text("private material\n", encoding="utf-8")
    run(["git", "init"], path)
    run(["git", "config", "user.name", "Test"], path)
    run(["git", "config", "user.email", "test@example.com"], path)
    run(["git", "add", "."], path)
    run(["git", "commit", "-m", "initial"], path)


def test_codebase_context_is_relevant_and_excludes_secret_paths(tmp_path: Path) -> None:
    module = load_module()
    initialize_repository(tmp_path)

    context, files = module.codebase_context(tmp_path, objective="repair worker test")

    assert "src/worker.py" in context
    assert "tests/test_worker.py" in context
    assert ".env" not in context
    assert "id_rsa" not in context
    assert "src/worker.py" in files


def test_claude_messages_request_uses_required_headers_and_text_blocks() -> None:
    module = load_module()
    captured = {}

    def urlopen(request, timeout=180):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "content": [
                    {"type": "text", "text": "```diff\ndiff --git a/a.py b/a.py\n```"}
                ]
            }
        )

    with patch.object(module.urllib.request, "urlopen", side_effect=urlopen):
        result = module.call_claude(
            api_key="anthropic-test-key",
            model="configured-claude-model",
            system="system rules",
            prompt="repository context",
        )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["X-api-key"] == "anthropic-test-key"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["body"]["model"] == "configured-claude-model"
    assert captured["body"]["system"] == "system rules"
    assert "diff --git" in result


def test_claude_request_requires_explicit_key_and_model() -> None:
    module = load_module()

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        module.call_claude(api_key="", model="model", system="s", prompt="p")
    with pytest.raises(RuntimeError, match="ANTHROPIC_MODEL"):
        module.call_claude(api_key="key", model="", system="s", prompt="p")


def test_executor_writes_validated_diff_without_applying_it(tmp_path: Path) -> None:
    module = load_module()
    target = tmp_path / "target"
    trusted = tmp_path / "trusted"
    target.mkdir()
    trusted.mkdir()
    initialize_repository(target)
    (trusted / "AGENTS.md").write_text("Keep changes bounded and tested.\n", encoding="utf-8")

    objective = tmp_path / "objective.txt"
    objective.write_text("Add a second return helper", encoding="utf-8")
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("Owner-requested change", encoding="utf-8")
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "regular_patch": {
                    "max_patch_bytes": 20000,
                    "max_changed_files": 4,
                    "protected_names": ["credentials.json", "secrets.json"],
                    "protected_paths": [],
                    "protected_prefixes": [".git/"],
                },
                "maintenance_patch": {
                    "max_patch_bytes": 20000,
                    "max_changed_files": 4,
                    "allowed_prefixes": ["src/", "tests/"],
                    "requires_test_change": False,
                    "human_approval_required": True,
                },
            }
        ),
        encoding="utf-8",
    )
    patch_output = tmp_path / "candidate.patch"
    report = tmp_path / "report.json"
    response = textwrap.dedent(
        """\
        ```diff
        diff --git a/src/worker.py b/src/worker.py
        --- a/src/worker.py
        +++ b/src/worker.py
        @@ -1,2 +1,5 @@
         def work():
             return 1
        +
        +def work_twice():
        +    return work() * 2
        ```
        """
    )

    with patch.object(module, "call_claude", return_value=response), patch.object(
        module.candidate.legacy,
        "memory_context",
        return_value="No verified memory matched.",
    ):
        status = module.main(
            [
                "--target",
                str(target),
                "--instructions-root",
                str(trusted),
                "--policy",
                str(policy),
                "--objective-file",
                str(objective),
                "--evidence",
                str(evidence),
                "--patch-output",
                str(patch_output),
                "--report",
                str(report),
                "--api-key",
                "test-key",
                "--model",
                "configured-model",
            ]
        )

    assert status == 0
    assert "work_twice" in patch_output.read_text(encoding="utf-8")
    assert "work_twice" not in (target / "src" / "worker.py").read_text(encoding="utf-8")
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "patch_generated"
    assert payload["patch_applied"] is False
    assert payload["commit_allowed"] is False
    assert payload["push_allowed"] is False
