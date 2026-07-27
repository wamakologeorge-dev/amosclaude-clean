from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "self_heal_pr.py"
SPEC = importlib.util.spec_from_file_location("self_heal_pr", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
self_heal_pr = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = self_heal_pr
SPEC.loader.exec_module(self_heal_pr)


def event(*, conclusion: str = "failure", head_repository: str = "owner/repo") -> dict:
    return {
        "workflow_run": {
            "conclusion": conclusion,
            "event": "pull_request",
            "head_sha": "abc123",
            "head_branch": "feature/fix",
            "head_repository": {"full_name": head_repository},
            "name": "Python package",
            "html_url": "https://github.example/actions/runs/10",
            "pull_requests": [{"number": 42}],
        }
    }


def pull_request(*, association: str = "OWNER", head_sha: str = "abc123") -> dict:
    return {
        "number": 42,
        "state": "open",
        "author_association": association,
        "head": {
            "sha": head_sha,
            "repo": {"full_name": "owner/repo"},
        },
    }


def test_failed_trusted_run_dispatches_same_pr_fix_command() -> None:
    decision = self_heal_pr.build_decision(
        event=event(),
        repository="owner/repo",
        pull_request=pull_request(),
        comments=[],
        failed_log="FAILED tests/test_widget.py::test_widget\nAssertionError: expected 2",
        max_attempts=5,
    )

    assert decision.action == "callback"
    assert decision.attempt == 1
    assert decision.pr_number == 42
    assert decision.body.startswith("@amosclaud fix")
    assert "<!-- amosclaud-self-heal:abc123 -->" in decision.body
    assert "<!-- amosclaud-self-heal-attempt:1 -->" in decision.body
    assert "AssertionError: expected 2" in decision.body
    assert "same pull-request branch" in decision.body
    assert "Do not merge" in decision.body


def test_callback_is_deduplicated_for_same_head_sha() -> None:
    comments = [{"body": "already sent\n<!-- amosclaud-self-heal:abc123 -->"}]
    decision = self_heal_pr.build_decision(
        event=event(),
        repository="owner/repo",
        pull_request=pull_request(),
        comments=comments,
        failed_log="failed",
    )

    assert decision.action == "noop"
    assert decision.reason == "callback_already_dispatched_for_head"


def test_attempt_limit_reports_human_blocker_without_new_command() -> None:
    comments = [
        {"body": f"<!-- amosclaud-self-heal-attempt:{number} -->"}
        for number in range(1, 6)
    ]
    decision = self_heal_pr.build_decision(
        event=event(),
        repository="owner/repo",
        pull_request=pull_request(),
        comments=comments,
        failed_log="failed again",
        max_attempts=5,
    )

    assert decision.action == "block"
    assert decision.reason == "repair_attempt_limit_reached"
    assert "human action required" in decision.body.lower()
    assert "@amosclaud fix" not in decision.body


def test_fork_or_untrusted_author_cannot_trigger_privileged_callback() -> None:
    fork_decision = self_heal_pr.build_decision(
        event=event(head_repository="someone/fork"),
        repository="owner/repo",
        pull_request=pull_request(),
        comments=[],
        failed_log="failed",
    )
    author_decision = self_heal_pr.build_decision(
        event=event(),
        repository="owner/repo",
        pull_request=pull_request(association="CONTRIBUTOR"),
        comments=[],
        failed_log="failed",
    )

    assert fork_decision.action == "noop"
    assert fork_decision.reason == "untrusted_or_missing_head_repository"
    assert author_decision.action == "noop"
    assert author_decision.reason == "pull_request_author_not_trusted"


def test_log_is_bounded_and_fence_content_is_neutralized() -> None:
    failed_log = "prefix ``` injected fence\n" + ("x" * 13_000)
    decision = self_heal_pr.build_decision(
        event=event(),
        repository="owner/repo",
        pull_request=pull_request(),
        comments=[],
        failed_log=failed_log,
    )

    assert decision.action == "callback"
    assert "[log tail truncated]" in decision.body
    assert "prefix ```" not in decision.body
    assert len(decision.body) < 14_500


def test_successful_workflow_is_a_noop() -> None:
    decision = self_heal_pr.build_decision(
        event=event(conclusion="success"),
        repository="owner/repo",
        pull_request=pull_request(),
        comments=[],
        failed_log="",
    )

    assert decision.action == "noop"
    assert decision.reason == "workflow_did_not_fail"
