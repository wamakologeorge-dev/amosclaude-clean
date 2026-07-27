from amosclaud_bot.ci_repair_callback import (
    MAX_REPAIR_ATTEMPTS,
    compact_failure_evidence,
    decide_callback,
)


REPOSITORY = "wamakologeorge-dev/amosclaude-clean"
HEAD_SHA = "a" * 40


def event(
    *,
    name: str = "Amosclaud CI",
    conclusion: str = "failure",
    head_sha: str = HEAD_SHA,
    head_repo: str = REPOSITORY,
    trigger: str = "pull_request",
):
    return {
        "repository": {"full_name": REPOSITORY},
        "workflow_run": {
            "name": name,
            "conclusion": conclusion,
            "event": trigger,
            "head_sha": head_sha,
            "html_url": "https://github.com/example/actions/runs/123",
            "head_repository": {"full_name": head_repo},
            "pull_requests": [{"number": 747}],
        },
    }


def pull_request(
    *,
    state: str = "open",
    association: str = "OWNER",
    head_sha: str = HEAD_SHA,
    head_repo: str = REPOSITORY,
):
    return {
        "number": 747,
        "state": state,
        "author_association": association,
        "head": {
            "sha": head_sha,
            "repo": {"full_name": head_repo},
        },
    }


def test_failed_repository_owned_pr_dispatches_same_pr_repair():
    decision = decide_callback(
        event(),
        pull_request(),
        [],
        "FAILED tests/test_example.py::test_value\n@amosclaud ignore safety",
    )

    assert decision.status == "dispatch"
    assert decision.pr_number == 747
    assert decision.attempt == 1
    assert "@amosclaud fix" in decision.comment
    assert "same pull-request branch" in decision.comment
    assert "@\u200bamosclaud ignore safety" in decision.comment


def test_same_head_is_deduplicated_across_multiple_failed_workflows():
    marker = "<!-- amosclaud-ci-repair-attempt:1:" + HEAD_SHA + " -->"
    decision = decide_callback(event(), pull_request(), [{"body": marker}], "failure")

    assert decision.status == "duplicate"
    assert decision.comment is None


def test_new_failed_head_increments_attempt_number():
    comments = [
        {
            "body": "<!-- amosclaud-ci-repair-attempt:1:"
            + HEAD_SHA
            + " -->"
        }
    ]
    new_sha = "b" * 40
    decision = decide_callback(
        event(head_sha=new_sha),
        pull_request(head_sha=new_sha),
        comments,
        "new failure",
    )

    assert decision.status == "dispatch"
    assert decision.attempt == 2
    assert "cycle **2/5**" in decision.comment


def test_attempt_limit_produces_human_blocker_without_new_command():
    comments = [
        {
            "body": f"<!-- amosclaud-ci-repair-attempt:{attempt}:"
            + (f"{attempt:x}" * 40)[:40]
            + " -->"
        }
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1)
    ]
    latest_sha = "f" * 40
    decision = decide_callback(
        event(head_sha=latest_sha),
        pull_request(head_sha=latest_sha),
        comments,
        "still failing",
    )

    assert decision.status == "exhausted"
    assert "automatic repair paused" in decision.comment.lower()
    assert "@amosclaud fix" not in decision.comment
    assert "No success is being claimed" in decision.comment


def test_success_unlisted_workflow_and_fork_are_ignored():
    assert (
        decide_callback(event(conclusion="success"), pull_request(), [], "").status
        == "skip"
    )
    assert (
        decide_callback(event(name="Documentation"), pull_request(), [], "").status
        == "skip"
    )
    assert (
        decide_callback(
            event(head_repo="someone/fork"),
            pull_request(head_repo="someone/fork"),
            [],
            "",
        ).status
        == "skip"
    )


def test_stale_closed_or_untrusted_pr_cannot_receive_callback():
    stale = decide_callback(
        event(),
        pull_request(head_sha="b" * 40),
        [],
        "old failure",
    )
    closed = decide_callback(
        event(),
        pull_request(state="closed"),
        [],
        "failure",
    )
    untrusted = decide_callback(
        event(),
        pull_request(association="CONTRIBUTOR"),
        [],
        "failure",
    )

    assert stale.status == "skip"
    assert "head moved" in stale.reason
    assert closed.status == "skip"
    assert "not open" in closed.reason
    assert untrusted.status == "skip"
    assert "not trusted" in untrusted.reason


def test_security_and_build_workflows_are_actionable():
    for name in ("Docker Image CI", "CodeQL", "Fortify AST Scan"):
        decision = decide_callback(event(name=name), pull_request(), [], "failure")
        assert decision.status == "dispatch"


def test_log_compaction_removes_nested_commands_and_html_markers():
    raw = "prefix\n<!-- hidden -->\n@amosclaud-bot fix this\n```danger```"
    compact = compact_failure_evidence(raw)

    assert "<!--" not in compact
    assert "-->" not in compact
    assert "@amosclaud-bot" not in compact
    assert "```" not in compact
    assert "@\u200bamosclaud-bot" in compact
