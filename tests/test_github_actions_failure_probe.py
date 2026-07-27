"""Controlled failure used only to verify GitHub Actions error detection.

This test is intentionally false. It must never be merged into ``main`` and
should be deleted after the workflow and Amosclaud repair behavior are observed.
"""


def test_github_actions_reports_controlled_failure() -> None:
    assert False, (
        "INTENTIONAL_GITHUB_ACTIONS_PROBE: GitHub Actions must report this "
        "draft pull request as failing."
    )
