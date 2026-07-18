"""Regression tests for Amosclaud executable code generation."""

from src.platform.ai_assistant import AIAssistant


def test_python_function_is_executable() -> None:
    assistant = AIAssistant()
    source = assistant.generate_function(
        "total", "Return a numeric total.", "python", return_type="int"
    )
    namespace: dict[str, object] = {}
    exec(source, namespace)
    assert namespace["total"]() == 0


def test_python_class_methods_are_executable() -> None:
    assistant = AIAssistant()
    source = assistant.generate_class(
        "Worker", "A generated worker.", methods=["run"], language="python"
    )
    namespace: dict[str, object] = {}
    exec(source, namespace)
    worker = namespace["Worker"]()
    assert worker.run() is None


def test_javascript_and_go_do_not_emit_unfinished_operations() -> None:
    assistant = AIAssistant()
    javascript = assistant.generate_function(
        "ready", "Return readiness.", "javascript", return_type="boolean"
    )
    golang = assistant.generate_function(
        "count", "Return a count.", "go", return_type="int"
    )
    combined = f"{javascript}\n{golang}".lower()
    assert "not implemented" not in combined
    assert "todo" not in combined
    assert "return false" in javascript
    assert "return 0" in golang


def test_generated_pytest_suite_contains_real_assertions(tmp_path) -> None:
    source_file = tmp_path / "sample.py"
    source_file.write_text("def double(value):\n    return value * 2\n", encoding="utf-8")
    tests = AIAssistant().generate_tests(str(source_file))
    lowered = tests.lower()
    assert "test_double_is_callable" in tests
    assert "assert callable" in tests
    assert "todo" not in lowered
    assert "pass" not in lowered
