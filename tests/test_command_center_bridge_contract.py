from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RECEIVER = ROOT / ".github" / "workflows" / "command-center-receiver.yml"
REVIEW_RECEIVER = ROOT / ".github" / "workflows" / "review-receiver.yml"
AUDIT = ROOT / ".github" / "workflows" / "real-operations-audit.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_command_receiver_keeps_trusted_source_and_allowlists() -> None:
    workflow = _read(RECEIVER)

    assert "test \"$SOURCE\" = 'wamakologeorge-dev/Amosclaud1'" in workflow
    assert "inspect|fix|verify|monitor" in workflow
    for repository in (
        "wamakologeorge-dev/amosclaude-clean",
        "wamakologeorge-dev/workspace",
        "wamakologeorge-dev/starter-workflows",
        "wamakologeorge-dev/Amosclaud1",
    ):
        assert repository in workflow
    assert '[[ "$ISSUE" =~ ^[0-9]+$ ]]' in workflow
    assert 'test -n "$OBJECTIVE"' in workflow
    assert 'test -n "$REQUEST_ID"' in workflow
    assert "group: amosclaud-command-${{ inputs.request_id }}" in workflow


def test_command_receiver_has_bounded_permissions_and_safe_checkout() -> None:
    workflow = _read(RECEIVER)

    assert re.search(r"permissions:\n  contents: read\n  actions: read\n", workflow)
    assert "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "persist-credentials: false" in workflow
    assert "git push --force" not in workflow


def test_review_receiver_keeps_separate_review_gate() -> None:
    workflow = _read(REVIEW_RECEIVER)

    assert 'test "$SOURCE" = "wamakologeorge-dev/Amosclaud1"' in workflow
    assert 'test "$ACTION" = "review"' in workflow
    assert '[[ "$ISSUE" =~ ^[0-9]+$ ]]' in workflow
    assert "group: amosclaud-review-${{ inputs.request_id }}" in workflow
    assert re.search(
        r"permissions:\n  contents: read\n  pull-requests: read\n  actions: read\n",
        workflow,
    )


def test_real_operations_audit_pins_actions_and_runs_bridge_contract() -> None:
    workflow = _read(AUDIT)

    assert "uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "tests/test_command_center_bridge_contract.py" in workflow
    assert not re.search(
        r"uses:\s+actions/(?:checkout|setup-python|upload-artifact)@v\d+",
        workflow,
    )
