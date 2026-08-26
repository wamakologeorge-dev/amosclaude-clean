from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from git import Repo

from amosclaud_autonomous_conversation import (
    ConversationState,
    JobExecutor,
    Objective,
)
from amosclaud_executor import ExecutorService, RepositoryTarget, SQLitePlanStore
from amosclaud_executor import service as executor_service


class FakeModel:
    def __init__(self, content: str) -> None:
        self.content = content

    def describe(self) -> dict[str, object]:
        return {"mode": "test-model", "endpoint_configured": True}

    def complete(self, _instruction: str, _evidence: list[str]) -> str:
        return self.content


def _repository(path, *, value: int = 1) -> Repo:
    path.mkdir()
    (path / "app.py").write_text(
        "def value() -> int:\n" f"    return {value}\n",
        encoding="utf-8",
    )
    tests = path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text(
        "from app import value\n\n\n" "def test_value() -> None:\n" "    assert value() == 2\n",
        encoding="utf-8",
    )
    (path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n" 'testpaths = ["tests"]\n',
        encoding="utf-8",
    )
    repo = Repo.init(path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Amosclaud Test")
        config.set_value("user", "email", "test@example.com")
    repo.git.add(A=True)
    repo.index.commit("Initial repository")
    return repo


def _proposal(value: int = 2) -> str:
    return json.dumps(
        {
            "plan": ["Correct the implementation", "Run the focused test"],
            "changes": [
                {
                    "path": "app.py",
                    "content": f"def value() -> int:\n    return {value}\n",
                    "reason": "Make the implementation satisfy the verified test.",
                }
            ],
            "commit_message": "Fix verified application behavior",
        }
    )


def test_plan_is_read_only_and_execute_requires_exact_confirmation(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    service = ExecutorService(model=FakeModel(_proposal()))
    target = RepositoryTarget(name="test-repository", workspace=workspace)

    planned = service.plan(target, "Fix the failing value test")
    assert planned.status == "planned"
    assert planned.plan_id
    assert repo.active_branch.name == "main"
    assert (workspace / "app.py").read_text(encoding="utf-8").endswith("return 1\n")

    blocked = service.execute(
        target,
        "Fix the failing value test",
        plan_id=planned.plan_id,
        confirmation="yes",
        delivery="branch",
    )
    assert blocked.status == "blocked"
    assert "exact confirmation 'Proceed'" in blocked.blockers[0]
    assert repo.active_branch.name == "main"

    completed = service.execute(
        target,
        "Fix the failing value test",
        plan_id=planned.plan_id,
        confirmation="Proceed",
        delivery="branch",
        author_name="Amosclaud Test",
        author_email="test@example.com",
    )
    assert completed.succeeded
    assert completed.branch and completed.branch.startswith("amosclaud/agent-")
    assert completed.commit == repo.head.commit.hexsha
    assert completed.changed_files == ["app.py"]
    assert all(check["passed"] for check in completed.checks)
    assert repo.git.show("main:app.py").strip().endswith("return 1")


def test_model_failure_cannot_claim_a_commit(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    model = FakeModel("not-json")
    service = ExecutorService(model=model)
    target = RepositoryTarget(name="test-repository", workspace=workspace)
    planned = service.plan(target, "Fix the failing value test")

    result = service.execute(
        target,
        "Fix the failing value test",
        plan_id=planned.plan_id,
        confirmation="Proceed",
        delivery="branch",
    )

    assert result.status == "failed"
    assert result.commit is None
    assert result.blockers
    assert repo.active_branch.name == "main"
    assert [head.name for head in repo.heads] == ["main"]
    assert (workspace / "app.py").read_text(encoding="utf-8").endswith("return 1\n")


def test_sqlite_plan_survives_a_new_service_instance(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    plan_db = tmp_path / "executor-plans.db"
    target = RepositoryTarget(name="test-repository", workspace=workspace)
    first_service = ExecutorService(
        model=FakeModel(_proposal()),
        plan_store=SQLitePlanStore(plan_db),
    )
    planned = first_service.plan(target, "Fix the failing value test")

    second_service = ExecutorService(
        model=FakeModel(_proposal()),
        plan_store=SQLitePlanStore(plan_db),
    )
    completed = second_service.execute(
        target,
        "Fix the failing value test",
        plan_id=planned.plan_id,
        confirmation="Proceed",
        delivery="branch",
        author_name="Amosclaud Test",
        author_email="test@example.com",
    )

    assert completed.succeeded
    assert repo.active_branch.name == completed.branch
    assert second_service.pending_plan_count == 0


def test_dirty_native_repository_is_blocked_before_model_execution(tmp_path) -> None:
    workspace = tmp_path / "repository"
    repo = _repository(workspace)
    (workspace / "app.py").write_text("def value() -> int:\n    return 99\n", encoding="utf-8")
    service = ExecutorService(model=FakeModel(_proposal()))
    target = RepositoryTarget(name="test-repository", workspace=workspace)

    result = service.plan(target, "Fix the failing value test")

    assert result.status == "blocked"
    assert "uncommitted changes" in result.blockers[0]
    assert repo.active_branch.name == "main"
    assert service.pending_plan_count == 0


def test_conversation_executor_returns_real_result_or_blocker(tmp_path) -> None:
    workspace = tmp_path / "repository"
    _repository(workspace)
    service = ExecutorService(model=FakeModel(_proposal()))
    executor = JobExecutor(service=service, workspace=workspace)
    state = ConversationState(
        conversation_id="conversation-test",
        user_name="George",
        objective=Objective.FIX,
        original_request="Fix the failing value test",
        answers={"failure": "tests/test_app.py fails because value returns 1"},
    )

    evidence, blockers = asyncio.run(executor.execute(state))

    assert not blockers
    assert any(item == "Executor status: completed." for item in evidence)
    assert any(item.startswith("Created commit:") for item in evidence)


def test_pull_request_publisher_uses_safe_metadata(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status_code = 201

        def json(self):
            return {"html_url": "https://github.com/example/repository/pull/8"}

    class Client:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, _url, *, headers, json):
            captured["headers"] = headers
            captured["json"] = json
            return Response()

    monkeypatch.setattr(executor_service.httpx, "Client", Client)
    service = ExecutorService(model=FakeModel(_proposal()))
    target = RepositoryTarget(
        name="repository",
        workspace=None,
        github_full_name="example/repository",
        github_token="token-that-must-not-appear-in-evidence",
    )
    runtime_result = SimpleNamespace(
        changed_files=["app.py"],
        checks=[{"name": "pytest", "passed": True, "summary": "1 passed"}],
    )

    url = service._create_pull_request(
        target,
        "amosclaud/agent-fix-1234",
        "main",
        "Fix the verified test",
        runtime_result,
        title=None,
        body=None,
        draft=True,
    )

    assert url.endswith("/pull/8")
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["head"] == "amosclaud/agent-fix-1234"
    assert payload["base"] == "main"
    assert payload["draft"] is True
    assert "token-that-must-not-appear-in-evidence" not in service.capabilities().__repr__()
