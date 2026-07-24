from pathlib import Path

from scripts.audit_real_operations import scan


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_status_only_production_behavior(tmp_path: Path) -> None:
    _write(tmp_path, "web/runtime.js", "const mode = 'status-only';\n")

    findings = scan(tmp_path)

    assert [(item.rule, item.path, item.line) for item in findings] == [
        ("status-only", "web/runtime.js", 1)
    ]


def test_ignores_html_input_placeholder_attributes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "web/form.html",
        '<input placeholder="Commit message"><button>Commit changes</button>\n',
    )

    assert scan(tmp_path) == []


def test_ignores_docs_tests_and_explicit_allowlist(tmp_path: Path) -> None:
    _write(tmp_path, "docs/design.md", "coming soon\n")
    _write(tmp_path, "tests/test_demo.py", "value = 'mock data'\n")
    _write(
        tmp_path,
        "amoscloud_ai/compat.py",
        "LEGACY_MESSAGE = 'not implemented'  # real-operation-audit: allow\n",
    )

    assert scan(tmp_path) == []


def test_detects_unfinished_operation_todo(tmp_path: Path) -> None:
    _write(tmp_path, "src/service.py", "# TODO: implement merge operation\n")

    findings = scan(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule == "todo-operation"
    assert findings[0].path == "src/service.py"
