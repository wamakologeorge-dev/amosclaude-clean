from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "repository_behavior.py"
SPEC = importlib.util.spec_from_file_location("repository_behavior", MODULE_PATH)
assert SPEC and SPEC.loader
repository_behavior = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repository_behavior)


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
            {"area:backend", "area:tests", "area:ci", "type:bug", "size:xs"}.issubset(labels)
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


if __name__ == "__main__":
    unittest.main()
