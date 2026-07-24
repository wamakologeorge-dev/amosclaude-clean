"""Tests for the Amosclaud Platform modules."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# SoftwareCreator
# ---------------------------------------------------------------------------

class TestSoftwareCreator:
    def setup_method(self):
        from src.platform.software_creator import SoftwareCreator
        self.creator = SoftwareCreator()

    def test_list_templates(self):
        templates = self.creator.list_templates()
        assert len(templates) > 0
        assert "web_api" in templates
        assert "library" in templates

    def test_create_web_api_project(self, tmp_path):
        from src.platform.software_creator import ProjectConfig, ProjectType
        config = ProjectConfig(
            name="test-api",
            project_type=ProjectType.WEB_API,
            description="A test API",
            output_dir=str(tmp_path),
        )
        result = self.creator.create_project(config)
        assert result.success
        assert len(result.files_created) > 0
        assert (tmp_path / "test-api" / "main.py").exists()
        assert (tmp_path / "test-api" / ".gitignore").exists()

    def test_create_library_project(self, tmp_path):
        from src.platform.software_creator import ProjectConfig, ProjectType
        config = ProjectConfig(
            name="mylib",
            project_type=ProjectType.LIBRARY,
            output_dir=str(tmp_path),
        )
        result = self.creator.create_project(config)
        assert result.success
        assert (tmp_path / "mylib" / "mylib" / "__init__.py").exists()

    def test_create_project_already_exists(self, tmp_path):
        from src.platform.software_creator import ProjectConfig, ProjectType
        (tmp_path / "existing").mkdir()
        config = ProjectConfig(
            name="existing",
            project_type=ProjectType.WEB_API,
            output_dir=str(tmp_path),
        )
        result = self.creator.create_project(config)
        assert not result.success

    def test_creation_history(self, tmp_path):
        from src.platform.software_creator import ProjectConfig, ProjectType
        config = ProjectConfig(
            name="hist-project",
            project_type=ProjectType.CLI_TOOL,
            output_dir=str(tmp_path),
        )
        self.creator.create_project(config)
        history = self.creator.get_creation_history()
        assert len(history) >= 1


# ---------------------------------------------------------------------------
# BuildEngine
# ---------------------------------------------------------------------------

class TestBuildEngine:
    def setup_method(self):
        from src.platform.build_engine import BuildEngine
        self.engine = BuildEngine()

    def test_detect_python_language(self, tmp_path):
        from src.platform.build_engine import Language
        (tmp_path / "setup.py").touch()
        lang = self.engine.detect_language(str(tmp_path))
        assert lang == Language.PYTHON

    def test_detect_nodejs_language(self, tmp_path):
        from src.platform.build_engine import Language
        (tmp_path / "package.json").write_text("{}")
        lang = self.engine.detect_language(str(tmp_path))
        assert lang == Language.NODEJS

    def test_detect_generic_language(self, tmp_path):
        from src.platform.build_engine import Language
        lang = self.engine.detect_language(str(tmp_path))
        assert lang == Language.GENERIC

    def test_clean(self, tmp_path):
        from src.platform.build_engine import BuildConfig, Language
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "artifact.whl").touch()
        config = BuildConfig(
            project_path=str(tmp_path),
            language=Language.PYTHON,
        )
        result = self.engine.clean(config)
        assert result
        assert not dist.exists()

    def test_build_history_empty_initially(self):
        assert self.engine.get_build_history() == []


# ---------------------------------------------------------------------------
# DeveloperTools
# ---------------------------------------------------------------------------

class TestDeveloperTools:
    def setup_method(self):
        from src.platform.developer_tools import DeveloperTools
        self.tools = DeveloperTools()

    def test_list_available_tools_returns_dict(self):
        available = self.tools.list_available_tools()
        assert isinstance(available, dict)
        assert "pytest" in available
        assert "flake8" in available

    def test_is_tool_available_python(self):
        # python is always available
        assert self.tools.is_tool_available("python3") or self.tools.is_tool_available("python")

    def test_is_tool_not_available(self):
        assert not self.tools.is_tool_available("nonexistent_tool_xyz_12345")

    def test_get_history_empty(self):
        assert self.tools.get_history() == []


# ---------------------------------------------------------------------------
# AIAssistant
# ---------------------------------------------------------------------------

class TestAIAssistant:
    def setup_method(self):
        from src.platform.ai_assistant import AIAssistant
        self.assistant = AIAssistant()

    def test_generate_python_function(self):
        snippet = self.assistant.generate_function(
            name="add",
            description="Add two integers.",
            language="python",
            return_type="int",
        )
        assert "def add" in snippet
        assert "Add two integers" in snippet

    def test_generate_python_class(self):
        snippet = self.assistant.generate_class(
            name="Calculator",
            description="A simple calculator.",
            methods=["add", "subtract"],
            language="python",
        )
        assert "class Calculator" in snippet
        assert "def add" in snippet

    def test_generate_tests(self, tmp_path):
        # Create a small Python file
        src_file = tmp_path / "utils.py"
        src_file.write_text("def double(x):\n    return x * 2\n")
        snippet = self.assistant.generate_tests(str(src_file))
        assert "test_double" in snippet

    def test_generate_docs(self, tmp_path):
        src_file = tmp_path / "app.py"
        src_file.write_text("def hello():\n    pass\n\nclass Foo:\n    pass\n")
        docs = self.assistant.generate_docs(str(src_file))
        assert "app" in docs
        assert "hello" in docs
        assert "Foo" in docs

    def test_review_file(self, tmp_path):
        src_file = tmp_path / "module.py"
        src_file.write_text("x = 1\n")
        result = self.assistant.review_file(str(src_file))
        assert result.file_path == str(src_file)
        assert isinstance(result.overall_score, float)
        assert 0 <= result.overall_score <= 10

    def test_suggest_refactoring(self, tmp_path):
        src_file = tmp_path / "big.py"
        # Write a file with high complexity indicators
        code = "def f():\n"
        for _ in range(20):
            code += "    if True:\n        pass\n"
        src_file.write_text(code)
        suggestions = self.assistant.suggest_refactoring(str(src_file))
        assert isinstance(suggestions, list)

    def test_history_records_operations(self, tmp_path):
        src_file = tmp_path / "m.py"
        src_file.write_text("def foo(): pass\n")
        self.assistant.review_file(str(src_file))
        self.assistant.generate_function("bar", "Do something")
        history = self.assistant.get_history()
        assert len(history) >= 2
