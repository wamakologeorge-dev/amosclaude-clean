from amosclaud_bot.approval_gate import (
    APPROVAL_CONSUMED_MARKER,
    APPROVAL_RECORD_MARKER,
    _approval_decision,
    _approval_source,
    _high_risk_files,
    _is_sensitive_objective,
    _normalize_objective,
)


class ApprovalBot:
    repository = "owner/repo"

    def __init__(self, pages):
        self.pages = pages

    def _request(self, method, path, payload=None):
        assert method == "GET"
        page = int(path.split("page=")[-1])
        return self.pages.get(page, [])


def test_sensitive_fix_objective_detection() -> None:
    assert _is_sensitive_objective("update production deployment workflow")
    assert _is_sensitive_objective("rotate authentication credential handling")
    assert not _is_sensitive_objective("fix typo in README")


def test_high_risk_pull_request_paths() -> None:
    files = [
        {"filename": ".github/workflows/deploy.yml"},
        {"filename": "src/service.py"},
        {"filename": "SECURITY.md"},
    ]
    assert _high_risk_files(files) == [".github/workflows/deploy.yml", "SECURITY.md"]


def test_approval_source_is_bound_to_exact_normalized_objective() -> None:
    first = _approval_source(474, " Production   deployment workflow ")
    same = _approval_source(474, "production deployment workflow")
    different = _approval_source(474, "production authentication workflow")

    assert first == same
    assert first != different
    assert first.startswith("issue-comment-474-")


def test_objective_normalization_is_stable() -> None:
    assert _normalize_objective("  Fix   Production WORKFLOW  ") == "fix production workflow"


def test_forged_human_approval_text_is_ignored() -> None:
    bot = ApprovalBot(
        {
            1: [
                {
                    "body": f"{APPROVAL_RECORD_MARKER}\n**Decision:** **APPROVED**",
                    "user": {"login": "random-user", "type": "User"},
                }
            ]
        }
    )
    assert _approval_decision(bot, 10) is None


def test_bot_generated_approval_record_is_trusted() -> None:
    bot = ApprovalBot(
        {
            1: [
                {
                    "body": f"{APPROVAL_RECORD_MARKER}\n**Decision:** **APPROVED**",
                    "user": {"login": "github-actions[bot]", "type": "Bot"},
                }
            ]
        }
    )
    assert _approval_decision(bot, 10) == "APPROVED"


def test_consumed_marker_on_later_page_wins() -> None:
    first_page = [
        {
            "body": f"{APPROVAL_RECORD_MARKER}\n**Decision:** **APPROVED**",
            "user": {"login": "github-actions[bot]", "type": "Bot"},
        }
    ] + [
        {"body": "noise", "user": {"login": "someone", "type": "User"}}
        for _ in range(99)
    ]
    bot = ApprovalBot(
        {
            1: first_page,
            2: [
                {
                    "body": APPROVAL_CONSUMED_MARKER,
                    "user": {"login": "github-actions[bot]", "type": "Bot"},
                }
            ],
        }
    )
    assert _approval_decision(bot, 10) == "CONSUMED"
