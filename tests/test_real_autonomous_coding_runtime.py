from __future__ import annotations

import json

from git import Repo

from amosclaud_os.agent.coding_runtime import AutonomousCodingRuntime


class FakeModel:
    def __init__(self, payload) -> None:
        self.payload = payload

    def describe(self) -> dict:
        return {
            "mode": "test-model",
            "endpoint_configured": True,
            "model": "fake-coding-model",
        }

    def complete(self, objective: str, evidence: list[str]) -> str:
        assert "Return exactly one JSON object" in objective
        assert any(item.startswith("REPOSITORY TREE") for item in evidence)
        return json.dumps(self.payload)


def _repository(path) -> Repo:
    path.mkdir()
    (path / "app.py").write_text(
        "def answer() -> int:\n"
        "    return 41\n",
        encoding="utf-8",
    )
    tests = path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text(
        "from app import answer\n\n\n"
        "def test_answer() -> None:\n"
        "    assert answer() == 42\n",
        encoding="utf-8",
    )
    (path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        "testpaths = [\"tests\"]\n",
        encoding="utf-8",
    )
    repo = Repo.init(path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "George")
        config.set_value("user", "email", "george@example.com")
    repo.git.add(A=True)
    repo.index.commit("Initial test repository")
    return repo


def _payload(value: int) -> dict:
    return {
        "plan": [
            "Inspect the failing answer test",
            "Correct the implementation",
            "Run repository verification",
        ],
        "changes": [
            {
                "path": "app.py",
                "content": (
                    "def answer() -> int:\n"
                    f"    return {value}\n"
                ),
                "reason": "Make the implementation satisfy the verified test.",
            }
        ],
        "commit_message": "Fix answer implementation",
    }


def test_runtime_creates_verified_branch_and_commit(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    runtime = AutonomousCodingRuntime(workspace, model=FakeModel(_payload(42)))

    result = runtime.run(
        objective="Fix the failing answer test",
        source_branch="main",
        author_name="George",
        author_email="george@example.com",
    )

    assert result.succeeded
    assert result.branch and result.branch.startswith("amosclaud/agent-")
    assert result.commit == repo.head.commit.hexsha
    assert repo.active_branch.name == result.branch
    assert (workspace / "app.py").read_text(encoding="utf-8").endswith("return 42\n")
    assert repo.git.show("main:app.py").strip().endswith("return 41")
    assert any(check["name"] == "pytest" and check["passed"] for check in result.checks)
    assert any(item.startswith("Created commit:") for item in result.evidence)


def test_runtime_rejects_path_escape_before_repository_mutation(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    payload = _payload(42)
    payload["changes"][0]["path"] = "../outside.py"
    runtime = AutonomousCodingRuntime(workspace, model=FakeModel(payload))

    result = runtime.run(
        objective="Write outside the repository",
        source_branch="main",
        author_name="George",
        author_email="george@example.com",
    )

    assert result.status == "failed"
    assert "escapes the controlled workspace" in (result.blocker or "")
    assert not (tmp_path / "outside.py").exists()
    assert repo.active_branch.name == "main"
    assert [head.name for head in repo.heads] == ["main"]


def test_runtime_rolls_back_when_verification_fails(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    runtime = AutonomousCodingRuntime(workspace, model=FakeModel(_payload(43)))

    result = runtime.run(
        objective="Change the answer incorrectly",
        source_branch="main",
        author_name="George",
        author_email="george@example.com",
    )

    assert result.status == "failed"
    assert "Verification failed" in (result.blocker or "")
    assert repo.active_branch.name == "main"
    assert [head.name for head in repo.heads] == ["main"]
    assert (workspace / "app.py").read_text(encoding="utf-8").endswith("return 41\n")
    assert any(check["name"] == "pytest" and not check["passed"] for check in result.checks)


def test_runtime_rejects_invalid_model_output_without_mutation(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    runtime = AutonomousCodingRuntime(workspace, model=FakeModel("not-json"))

    result = runtime.run(
        objective="Fix the repository",
        source_branch="main",
        author_name="George",
        author_email="george@example.com",
    )

    assert result.status == "failed"
    assert "JSON object" in (result.blocker or "")
    assert repo.active_branch.name == "main"
    assert [head.name for head in repo.heads] == ["main"]
