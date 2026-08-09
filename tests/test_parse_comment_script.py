from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "parse_comment.py"


def load_module():
    spec = importlib.util.spec_from_file_location("parse_comment_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payload(body: str, association: str = "OWNER") -> dict[str, object]:
    return {
        "comment": {"body": body, "author_association": association, "id": 123},
        "issue": {"number": 17, "pull_request": {"url": "example"}},
    }


def test_patch_alias_routes_to_claude_executor() -> None:
    module = load_module()

    result = module.parse_event(payload("@amosclaud patch add a regression test"))

    assert result.recognized is True
    assert result.command == "fix"
    assert result.objective == "add a regression test"
    assert result.authorized_write is True
    assert result.patch_executor is True
    assert result.source_format == "claude-patch-alias"
    assert result.pull_request is True


def test_structured_owner_task_uses_existing_native_fixer_path() -> None:
    module = load_module()

    result = module.parse_event(
        payload(
            "TASK: Create .github/scripts/parse_comment.py\n"
            "RESTRICTION: never hardcode secrets\n"
            "OUTPUT: include focused tests"
        )
    )

    assert result.command == "fix"
    assert result.authorized_write is True
    assert result.patch_executor is False
    assert "Create .github/scripts/parse_comment.py" in result.objective
    assert "do not embed sensitive values" in result.objective
    assert result.source_format == "trusted-owner-directive"


def test_normal_fix_command_stays_on_native_fixer_path() -> None:
    module = load_module()

    result = module.parse_event(payload("@amosclaud fix the failing unit test"))

    assert result.command == "fix"
    assert result.authorized_write is True
    assert result.patch_executor is False


def test_untrusted_structured_comment_is_not_a_command() -> None:
    module = load_module()

    result = module.parse_event(payload("TASK: modify the repository", "NONE"))

    assert result.recognized is False
    assert result.command is None
    assert result.authorized_write is False
    assert result.patch_executor is False


def test_read_only_review_never_routes_to_patch_executor() -> None:
    module = load_module()

    result = module.parse_event(payload("@amosclaud review this pull request"))

    assert result.command == "review"
    assert result.write_request is False
    assert result.authorized_write is False
    assert result.patch_executor is False


def test_public_result_does_not_repeat_owner_objective() -> None:
    module = load_module()
    result = module.parse_event(payload("@amosclaud patch internal task details"))

    public = result.public_dict()

    assert public["objective"] == "[stored locally]"
    assert "internal task details" not in str(public)
