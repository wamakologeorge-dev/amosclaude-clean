"""AI-assisted code generation, review, documentation, and test creation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.ai.agent_contingency import AIAgentContingency
from src.core.code_analyzer import CodeAnalyzer

logger = logging.getLogger(__name__)


class SuggestionType(Enum):
    """Category of an AI suggestion."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    REFACTORING = "refactoring"
    DOCUMENTATION = "documentation"
    BUG_FIX = "bug_fix"
    PERFORMANCE = "performance"
    SECURITY = "security"
    TEST_GENERATION = "test_generation"


@dataclass
class AISuggestion:
    """A single suggestion produced by the assistant."""

    suggestion_type: SuggestionType
    title: str
    description: str
    code_snippet: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.suggestion_type.value,
            "title": self.title,
            "description": self.description,
            "code_snippet": self.code_snippet,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "confidence": self.confidence,
        }


@dataclass
class ReviewResult:
    """Result of a code review."""

    file_path: str
    suggestions: List[AISuggestion]
    overall_score: float
    summary: str
    reviewed_at: datetime = field(default_factory=datetime.now)

    @property
    def has_issues(self) -> bool:
        return any(
            item.suggestion_type in (SuggestionType.BUG_FIX, SuggestionType.SECURITY)
            for item in self.suggestions
        )


class AIAssistant:
    """Developer assistant that produces executable starter code and evidence."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}
        self._analyzer = CodeAnalyzer()
        self._contingency = AIAgentContingency(
            config={"max_retries": 3, "retry_delay": 2}
        )
        self._history: List[Dict[str, Any]] = []

    def review_file(self, file_path: str) -> ReviewResult:
        """Analyse a file and return concrete review suggestions."""
        logger.info("Reviewing file: %s", file_path)
        analysis = self._analyzer.analyze_file(file_path)
        suggestions = self._generate_review_suggestions(file_path, analysis)
        score = self._calculate_quality_score(suggestions)
        result = ReviewResult(
            file_path=file_path,
            suggestions=suggestions,
            overall_score=score,
            summary=self._build_review_summary(analysis, suggestions),
        )
        self._history.append({"type": "review", "file": file_path, "score": score})
        return result

    def review_directory(self, dir_path: str) -> List[ReviewResult]:
        """Review every Python file below a directory."""
        path = Path(dir_path)
        if not path.is_dir():
            raise ValueError(f"Directory does not exist: {dir_path}")
        results = [self.review_file(str(item)) for item in sorted(path.rglob("*.py"))]
        self._history.append(
            {"type": "review_directory", "directory": dir_path, "files": len(results)}
        )
        return results

    def generate_function(
        self,
        name: str,
        description: str,
        language: str = "python",
        params: Optional[List[Dict[str, str]]] = None,
        return_type: str = "None",
    ) -> str:
        """Generate a syntactically complete function with a safe default result."""
        self._validate_identifier(name)
        params = params or []
        normalized = language.lower()
        if normalized == "python":
            snippet = self._generate_python_function(name, description, params, return_type)
        elif normalized in {"javascript", "typescript"}:
            snippet = self._generate_js_function(
                name, description, params, return_type, normalized
            )
        elif normalized == "go":
            snippet = self._generate_go_function(name, description, params, return_type)
        else:
            raise ValueError(f"Unsupported language: {language}")
        self._history.append(
            {"type": "generate_function", "name": name, "language": normalized}
        )
        return snippet

    def generate_class(
        self,
        name: str,
        description: str,
        methods: Optional[List[str]] = None,
        language: str = "python",
    ) -> str:
        """Generate a complete class whose methods return safe default values."""
        self._validate_identifier(name)
        method_names = methods or []
        for method in method_names:
            self._validate_identifier(method)
        normalized = language.lower()
        if normalized == "python":
            snippet = self._generate_python_class(name, description, method_names)
        elif normalized in {"javascript", "typescript"}:
            body = "\n".join(
                f"  {method}() {{ return null; }}" for method in method_names
            )
            snippet = f"/** {description} */\nclass {name} {{\n{body}\n}}\n"
        else:
            raise ValueError(f"Unsupported class language: {language}")
        self._history.append(
            {"type": "generate_class", "name": name, "language": normalized}
        )
        return snippet

    def generate_tests(self, file_path: str, framework: str = "pytest") -> str:
        """Generate executable discovery tests for functions and classes in a module."""
        if framework != "pytest":
            raise ValueError(f"Unsupported test framework: {framework}")
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"Source file does not exist: {file_path}")
        analysis = self._analyzer.analyze_file(file_path)
        snippet = self._generate_pytest_suite(
            path.stem,
            list(analysis.get("functions", [])),
            list(analysis.get("classes", [])),
        )
        self._history.append({"type": "generate_tests", "file": file_path})
        return snippet

    def generate_docs(self, file_path: str) -> str:
        """Generate Markdown documentation from static analysis evidence."""
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"Source file does not exist: {file_path}")
        analysis = self._analyzer.analyze_file(file_path)
        lines = [
            f"# `{path.stem}`\n",
            "*Generated by Amosclaud-AI from repository source analysis.*\n",
            f"**Complexity score:** {analysis.get('complexity', 'N/A')}\n",
        ]
        functions = analysis.get("functions", [])
        classes = analysis.get("classes", [])
        imports = analysis.get("imports", [])
        if classes:
            lines.append("## Classes\n")
            lines.extend(f"- `{item}`" for item in classes)
        if functions:
            lines.append("\n## Functions\n")
            lines.extend(f"- `{item}()`" for item in functions)
        if imports:
            lines.append("\n## Imports\n")
            lines.extend(f"- `{item}`" for item in imports)
        self._history.append({"type": "generate_docs", "file": file_path})
        return "\n".join(lines) + "\n"

    def suggest_refactoring(self, file_path: str) -> List[AISuggestion]:
        """Return evidence-based refactoring suggestions."""
        analysis = self._analyzer.analyze_file(file_path)
        suggestions: List[AISuggestion] = []
        complexity = analysis.get("complexity", 1)
        functions = analysis.get("functions", [])
        if complexity > 10:
            suggestions.append(
                AISuggestion(
                    suggestion_type=SuggestionType.REFACTORING,
                    title="High cyclomatic complexity",
                    description=(
                        f"The module has a complexity score of {complexity}. "
                        "Extract focused functions and verify each path with tests."
                    ),
                    file_path=file_path,
                    confidence=0.9,
                )
            )
        if len(functions) > 20:
            suggestions.append(
                AISuggestion(
                    suggestion_type=SuggestionType.REFACTORING,
                    title="Split the module",
                    description=f"The module defines {len(functions)} functions.",
                    file_path=file_path,
                    confidence=0.8,
                )
            )
        self._history.append({"type": "refactor", "file": file_path})
        return suggestions

    def get_history(self) -> List[Dict[str, Any]]:
        """Return operations performed in this process."""
        return list(self._history)

    @staticmethod
    def _validate_identifier(name: str) -> None:
        if not name or not name.isidentifier():
            raise ValueError(f"Invalid identifier: {name!r}")

    def _generate_review_suggestions(
        self, file_path: str, analysis: Dict[str, Any]
    ) -> List[AISuggestion]:
        if not analysis:
            return []
        suggestions: List[AISuggestion] = []
        complexity = analysis.get("complexity", 1)
        lines = analysis.get("lines", 0)
        functions = analysis.get("functions", [])
        if complexity > 15:
            suggestions.append(
                AISuggestion(
                    suggestion_type=SuggestionType.REFACTORING,
                    title="Reduce cyclomatic complexity",
                    description=f"Complexity {complexity} exceeds the recommended maximum of 15.",
                    file_path=file_path,
                    confidence=0.95,
                )
            )
        if lines > 500:
            suggestions.append(
                AISuggestion(
                    suggestion_type=SuggestionType.REFACTORING,
                    title="Large file detected",
                    description=f"File has {lines} lines; split it into cohesive modules.",
                    file_path=file_path,
                    confidence=0.8,
                )
            )
        if not functions:
            suggestions.append(
                AISuggestion(
                    suggestion_type=SuggestionType.CODE_REVIEW,
                    title="No top-level functions detected",
                    description="Confirm that module-level statements are intentional.",
                    file_path=file_path,
                    confidence=0.7,
                )
            )
        return suggestions

    @staticmethod
    def _calculate_quality_score(suggestions: List[AISuggestion]) -> float:
        score = 10.0
        penalties = {
            SuggestionType.BUG_FIX: 2.0,
            SuggestionType.SECURITY: 3.0,
            SuggestionType.REFACTORING: 1.0,
        }
        for suggestion in suggestions:
            score -= penalties.get(suggestion.suggestion_type, 0.5) * suggestion.confidence
        return max(0.0, round(score, 1))

    @staticmethod
    def _build_review_summary(
        analysis: Dict[str, Any], suggestions: List[AISuggestion]
    ) -> str:
        if not analysis:
            return "Unable to analyse file."
        return (
            f"Analysed {analysis.get('lines', 0)} lines, "
            f"{len(analysis.get('functions', []))} function(s), "
            f"{len(analysis.get('classes', []))} class(es). "
            f"Complexity: {analysis.get('complexity', 0)}. "
            f"Found {len(suggestions)} suggestion(s)."
        )

    @staticmethod
    def _python_default(return_type: str) -> str:
        normalized = return_type.strip().lower().replace(" ", "")
        if normalized in {"none", "nonetype", "optional", "any"} or "optional[" in normalized:
            return "None"
        if normalized in {"bool", "boolean"}:
            return "False"
        if normalized in {"int", "integer"}:
            return "0"
        if normalized in {"float", "double"}:
            return "0.0"
        if normalized in {"str", "string"}:
            return '""'
        if normalized.startswith(("list", "sequence", "tuple", "set")):
            return "[]"
        if normalized.startswith(("dict", "mapping")):
            return "{}"
        return "None"

    def _generate_python_function(
        self,
        name: str,
        description: str,
        params: List[Dict[str, str]],
        return_type: str,
    ) -> str:
        param_str = ", ".join(
            f"{item.get('name', 'arg')}: {item.get('type', 'Any')}" for item in params
        )
        return (
            f"def {name}({param_str}) -> {return_type}:\n"
            f'    """{description}"""\n'
            f"    return {self._python_default(return_type)}\n"
        )

    @staticmethod
    def _js_default(return_type: str) -> str:
        normalized = return_type.strip().lower()
        if normalized in {"boolean", "bool"}:
            return "false"
        if normalized in {"number", "int", "integer", "float"}:
            return "0"
        if normalized in {"string", "str"}:
            return "''"
        if "[]" in normalized or normalized.startswith("array"):
            return "[]"
        if normalized.startswith(("object", "record", "map")):
            return "{}"
        return "null"

    def _generate_js_function(
        self,
        name: str,
        description: str,
        params: List[Dict[str, str]],
        return_type: str,
        language: str,
    ) -> str:
        rendered = []
        for item in params:
            param_name = item.get("name", "arg")
            rendered.append(
                f"{param_name}: {item.get('type', 'unknown')}"
                if language == "typescript"
                else param_name
            )
        type_annotation = f": {return_type}" if language == "typescript" else ""
        return (
            f"/** {description} */\n"
            f"function {name}({', '.join(rendered)}){type_annotation} {{\n"
            f"  return {self._js_default(return_type)};\n"
            "}\n"
        )

    @staticmethod
    def _go_default(return_type: str) -> str:
        normalized = return_type.strip()
        if normalized in {"", "void"}:
            return ""
        if normalized == "bool":
            return "false"
        if normalized.startswith(("int", "uint", "float", "complex")):
            return "0"
        if normalized == "string":
            return '""'
        if normalized.startswith(("[]", "map[", "*", "chan ", "func(", "interface{")):
            return "nil"
        return f"*new({normalized})"

    def _generate_go_function(
        self,
        name: str,
        description: str,
        params: List[Dict[str, str]],
        return_type: str,
    ) -> str:
        rendered = ", ".join(
            f"{item.get('name', 'arg')} {item.get('type', 'interface{}')}" for item in params
        )
        exported = name[0].upper() + name[1:]
        default = self._go_default(return_type)
        return_line = f"\treturn {default}\n" if default else ""
        return (
            f"// {exported} {description}\n"
            f"func {exported}({rendered}) {return_type} {{\n"
            f"{return_line}"
            "}\n"
        )

    def _generate_python_class(
        self, name: str, description: str, methods: List[str]
    ) -> str:
        lines = [
            f"class {name}:",
            f'    """{description}"""',
            "",
            "    def __init__(self) -> None:",
            "        self.created_at = None",
        ]
        for method in methods:
            lines.extend(
                [
                    "",
                    f"    def {method}(self):",
                    f'        """Execute {method} with a safe default result."""',
                    "        return None",
                ]
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _generate_pytest_suite(
        module_name: str, functions: List[str], classes: List[str]
    ) -> str:
        lines = [
            f'"""Generated discovery tests for {module_name}."""',
            "",
            "import inspect",
            f"import {module_name} as module_under_test",
            "",
        ]
        for function_name in functions:
            lines.extend(
                [
                    f"def test_{function_name}_is_callable():",
                    f"    target = getattr(module_under_test, {function_name!r})",
                    "    assert callable(target)",
                    "    assert inspect.isfunction(target)",
                    "",
                ]
            )
        for class_name in classes:
            test_name = class_name.lower()
            lines.extend(
                [
                    f"def test_{test_name}_is_class():",
                    f"    target = getattr(module_under_test, {class_name!r})",
                    "    assert inspect.isclass(target)",
                    "",
                ]
            )
        if not functions and not classes:
            lines.extend(
                [
                    "def test_module_imports():",
                    "    assert module_under_test is not None",
                    "",
                ]
            )
        return "\n".join(lines)
