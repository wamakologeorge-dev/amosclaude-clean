from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "repository_behavior.py"
)
WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "behavior-automation.yml"
)
SPEC = importlib.util.spec_from_file_location("repository_behavior", MODULE_PATH)
assert SPEC and SPEC.loader
repository_behavior = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_behavior)


class RecordingClient:
    def __init__(self, labels: set[str] | None = None) -> None:
        self.labels = labels or set()
        self.requests: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        *,
        expected: tuple[int, ...] = (200,),
    ) -> object:
        del payload, expected
        self.requests.append((method, path))
        if method == "GET" and path.startswith("/issues/"):
            return {"labels": [{"name": label} for label in sorted(self.labels)]}
        if method == "DELETE":
            return []
        raise AssertionError(f"Unexpected request: {method} {path}")


class RepositoryBehaviorClassificationTests(unittest.TestCase):
    def test_issue_classification_detects_bug_and_deployment(self) -> None:
        labels = repository_behavior.classify_issue(
            "Railway deployment failed",
            "The production Docker release returns an error.",
        )
        self.assertIn("type:bug", labels)
        self.assertIn("area:deployment", labels)

    def test_issue_without_signal_needs_triage(self) -> None:
        self.assertEqual(
            repository_behavior.classify_issue("Question", "Please review this."),
            {"status:needs-triage"},
        )

    def test_pull_request_labels_paths_size_and_security(self) -> None:
        labels = repository_behavior.classify_pull_request(
            [
                "amoscloud_ai/api/routes/auth.py",
                "tests/test_auth.py",
                ".github/workflows/security.yml",
            ],
            title="Fix authentication checks",
        )
        self.assertTrue(
            {
                "area:backend",
                "area:tests",
                "area:ci",
                "type:bug",
                "size:xs",
            }.issubset(labels)
        )
        self.assertIn("security-sensitive", labels)

    def test_dependency_pull_request_is_detected(self) -> None:
        labels = repository_behavior.classify_pull_request(
            ["requirements.txt"],
            title="Bump dependency",
            author="dependabot[bot]",
        )
        self.assertIn("type:dependencies", labels)
        self.assertIn("size:xs", labels)

    def test_documentation_only_pull_request(self) -> None:
        labels = repository_behavior.classify_pull_request(
            ["README.md", "docs/OPERATIONS.md"],
            title="Update docs",
        )
        self.assertIn("area:docs", labels)
        self.assertNotIn("area:backend", labels)


class RepositoryBehaviorRefreshTests(unittest.TestCase):
    def test_refresh_without_stale_label_is_a_read_only_noop(self) -> None:
        client = RecordingClient()

        refreshed = repository_behavior.refresh_item(client, 41)

        self.assertFalse(refreshed)
        self.assertEqual(client.requests, [("GET", "/issues/41")])

    def test_refresh_removes_only_the_stale_label(self) -> None:
        client = RecordingClient({"type:bug", "status:stale"})

        refreshed = repository_behavior.refresh_item(client, 42)

        self.assertTrue(refreshed)
        self.assertEqual(
            client.requests,
            [
                ("GET", "/issues/42"),
                ("DELETE", "/issues/42/labels/status%3Astale"),
            ],
        )

    def test_refresh_command_does_not_provision_repository_labels(self) -> None:
        client = RecordingClient()
        output = io.StringIO()

        with (
            mock.patch.object(repository_behavior, "GitHubClient", return_value=client),
            mock.patch.object(repository_behavior, "ensure_labels") as ensure_labels,
            redirect_stdout(output),
        ):
            status = repository_behavior.main(
                [
                    "--repository",
                    "owner/repository",
                    "--token",
                    "token",
                    "refresh",
                    "--number",
                    "43",
                ]
            )

        self.assertEqual(status, 0)
        ensure_labels.assert_not_called()
        self.assertEqual(output.getvalue().strip(), '{"refreshed": false}')

    def test_workflow_ignores_automation_comments(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("github.event.comment.user.type != 'Bot'", workflow)


if __name__ == "__main__":
    unittest.main()
