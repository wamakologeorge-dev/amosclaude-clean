"""Regression proof for the controlled GitHub Actions failure probe.

The previous revision intentionally failed so the repository could prove that
GitHub Actions and Amosclaud detect a real pytest error. This repaired version
keeps the probe marker while preventing the unconditional failure from being
reintroduced.
"""

from pathlib import Path


PROBE_MARKER = "INTENTIONAL_GITHUB_ACTIONS_PROBE"


def test_github_actions_failure_probe_is_repaired() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    unconditional_failure = "assert " + "False"

    assert PROBE_MARKER in source
    assert unconditional_failure not in source
