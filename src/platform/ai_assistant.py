"""
AIAssistant — Amosclaud-AI powered code generation, review, and suggestions.

Provides high-level AI helpers that integrate with the existing Amosclaud-AI
infrastructure (code analysis, contingency handling) and expose a simple
interface for generating, reviewing, documenting, and refactoring code.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.code_analyzer import CodeAnalyzer
from src.ai.agent_contingency import AIAgentContingency, ContingencyLevel

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
    """A single suggestion produced by the AI assistant."""
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
    """Result of an AI code review."""
    file_path: str
    suggestions: List[AISuggestion]
    overall_score: float
    summary: str
    reviewed_at: datetime = field(default_factory=datetime.now)

    @property
    def has_issues(self) -> bool:
        return any(
            s.suggestion_type in (SuggestionType.BUG_FIX, SuggestionType.SECURITY)
            for s in self.suggestions
        )


class AIAssistant:
    """
    Amosclaud-AI assistant for developer productivity.

    Wraps the existing :class:`~src.core.code_analyzer.CodeAnalyzer` and
    :class:`~src.ai.agent_contingency.AIAgentContingency` components and
    provides high-level methods for common AI-assisted developer tasks.

    Usage::

        assistant = AIAssistant()

        # Review a file
        review = assistant.review_file("src/app.py")
        for suggestion in review.suggestions:
            print(suggestion.title)

        # Generate a new function
        snippet = assistant.generate_function(
            name="calculate_total",
            description="Sum a list of floats and return the result.",
            language="python",
        )
        print(snippet)

        # Generate tests for a file
        tests = assistant.generate_tests("src/app.py")
        print(tests)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = config or {}
        self._analyzer = CodeAnalyzer()
        self._contingency = AIAgentContingency(
            config={"max_retries": 3, "retry_delay": 2}
        )
        self._history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Code review
    # ------------------------------------------------------------------

    def review_file(self, file_path: str) -> ReviewResult:
        """Analyse *file_path* and return AI-powered suggestions."""
        logger.info("Reviewing file: %s", file_path)
        analysis = self._analyzer.analyze_file(file_path)
        suggestions = self._generate_review_suggestions(file_path, analysis)
        score = self._calculate_quality_score(analysis, suggestions)
        summary = self._build_review_summary(analysis, suggestions)

        result = ReviewResult(
            file_path=file_path,
            suggestions=suggestions,
            overall_score=score,
            summary=summary,
        )
        self._history.append({"type": "review", "file": file_path, "score": score})
        logger.info("Review complete — score %.1f/10, %d suggestion(s)", score, len(suggestions))
        return result

    def review_directory(self, dir_path: str) -> List[ReviewResult]:
        """Review every Python file inside *dir_path*."""
        path = Path(dir_path)
        results: List[ReviewResult] = []
        for py_file in path.rglob("*.py"):
            results.append(self.review_file(str(py_file)))
        logger.info("Directory review complete — %d file(s) reviewed", len(results))
        return results

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    def generate_function(
        self,
        name: str,
        description: str,
        language: str = "python",
        params: Optional[List[Dict[str, str]]] = None,
        return_type: str = "None",
    ) -> str:
        """
        Generate a function stub based on *description*.

        Returns a formatted code snippet string.
        """
        logger.info("Generating function: %s (%s)", name, language)
        params = params or []

        if language == "python":
            snippet = self._generate_python_function(name, description, params, return_type)
        elif language in ("javascript", "typescript"):
            snippet = self._generate_js_function(name, description, params, return_type, language)
        elif language == "go":
            snippet = self._generate_go_function(name, description, params, return_type)
        else:
            snippet = f"// Generated function: {name}\n// {description}\nfunction {name}() {{}}"

        self._history.append({"type": "generate_function", "name": name, "language": language})
        return snippet

    def generate_class(
        self,
        name: str,
        description: str,
        methods: Optional[List[str]] = None,
        language: str = "python",
    ) -> str:
        """Generate a class stub with optional method stubs."""
        logger.info("Generating class: %s (%s)", name, language)
        methods = methods or []

        if language == "python":
            snippet = self._generate_python_class(name, description, methods)
        else:
            snippet = f"// Generated class: {name}\n// {description}\nclass {name} {{}}"

        self._history.append({"type": "generate_class", "name": name, "language": language})
        return snippet

    def generate_tests(
        self,
        file_path: str,
        framework: str = "pytest",
    ) -> str:
        """Generate unit tests for the code in *file_path*."""
        logger.info("Generating tests for: %s (%s)", file_path, framework)
        analysis = self._analyzer.analyze_file(file_path)
        module_name = Path(file_path).stem
        functions = analysis.get("functions", [])
        classes = analysis.get("classes", [])

        if framework == "pytest":
            snippet = self._generate_pytest_suite(module_name, functions, classes)
        else:
            snippet = f"# Tests for {module_name}\n# Framework: {framework}\n"

        self._history.append({"type": "generate_tests", "file": file_path})
        return snippet

    # ------------------------------------------------------------------
    # Documentation generation
    # ------------------------------------------------------------------

    def generate_docs(self, file_path: str) -> str:
        """Generate Markdown documentation for a Python module."""
        logger.info("Generating docs for: %s", file_path)
        analysis = self._analyzer.analyze_file(file_path)
        module_name = Path(file_path).stem
        lines = [
            f"# `{module_name}`\n",
            f"*Auto-generated by Amosclaud-AI*\n",
            f"**Complexity score:** {analysis.get('complexity', 'N/A')}\n",
        ]

        if analysis.get("classes"):
            lines.append("## Classes\n")
            for cls in analysis["classes"]:
                lines.append(f"### `{cls}`\n")

        if analysis.get("functions"):
            lines.append("## Functions\n")
            for fn in analysis["functions"]:
                lines.append(f"### `{fn}()`\n")

        if analysis.get("imports"):
            lines.append("## Imports\n")
            for imp in analysis["imports"]:
                lines.append(f"- `{imp}`\n")

        self._history.append({"type": "generate_docs", "file": file_path})
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Refactoring suggestions
    # ------------------------------------------------------------------

    def suggest_refactoring(self, file_path: str) -> List[AISuggestion]:
        """Return refactoring suggestions for *file_path*."""
        analysis = self._analyzer.analyze_file(file_path)
        suggestions: List[AISuggestion] = []
        complexity = analysis.get("complexity", 1)

        if complexity > 10:
            suggestions.append(AISuggestion(
                suggestion_type=SuggestionType.REFACTORING,
                title="High cyclomatic complexity",
                description=(
                    f"The module has a complexity score of {complexity}. "
                    "Consider extracting logic into smaller, focused functions."
                ),
                file_path=file_path,
                confidence=0.9,
            ))

        functions = analysis.get("functions", [])
        if len(functions) > 20:
            suggestions.append(AISuggestion(
                suggestion_type=SuggestionType.REFACTORING,
                title="Consider splitting the module",
                description=(
                    f"This module defines {len(functions)} functions. "
                    "Splitting into sub-modules improves maintainability."
                ),
                file_path=file_path,
                confidence=0.8,
            ))

        self._history.append({"type": "refactor", "file": file_path})
        return suggestions

    def get_history(self) -> List[Dict[str, Any]]:
        """Return the list of AI operations performed in this session."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Internal helpers — review
    # ------------------------------------------------------------------

    def _generate_review_suggestions(
        self, file_path: str, analysis: Dict[str, Any]
    ) -> List[AISuggestion]:
        suggestions: List[AISuggestion] = []
        if not analysis:
            return suggestions

        complexity = analysis.get("complexity", 1)
        lines = analysis.get("lines", 0)
        functions = analysis.get("functions", [])

        if complexity > 15:
            suggestions.append(AISuggestion(
                suggestion_type=SuggestionType.REFACTORING,
                title="Reduce cyclomatic complexity",
                description=f"Complexity score {complexity} exceeds the recommended maximum of 15.",
                file_path=file_path,
                confidence=0.95,
            ))

        if lines > 500:
            suggestions.append(AISuggestion(
                suggestion_type=SuggestionType.REFACTORING,
                title="Large file detected",
                description=f"File has {lines} lines. Consider splitting into smaller modules.",
                file_path=file_path,
                confidence=0.8,
            ))

        if not functions:
            suggestions.append(AISuggestion(
                suggestion_type=SuggestionType.CODE_REVIEW,
                title="No functions detected",
                description="The module contains no top-level functions. Consider adding structure.",
                file_path=file_path,
                confidence=0.7,
            ))

        if len(functions) > 0 and complexity / len(functions) < 1.2:
            suggestions.append(AISuggestion(
                suggestion_type=SuggestionType.DOCUMENTATION,
                title="Add docstrings",
                description="Functions appear to lack docstrings. Document public interfaces.",
                file_path=file_path,
                confidence=0.75,
            ))

        return suggestions

    def _calculate_quality_score(
        self, analysis: Dict[str, Any], suggestions: List[AISuggestion]
    ) -> float:
        score = 10.0
        for suggestion in suggestions:
            if suggestion.suggestion_type == SuggestionType.BUG_FIX:
                score -= 2.0 * suggestion.confidence
            elif suggestion.suggestion_type == SuggestionType.SECURITY:
                score -= 3.0 * suggestion.confidence
            elif suggestion.suggestion_type == SuggestionType.REFACTORING:
                score -= 1.0 * suggestion.confidence
            else:
                score -= 0.5 * suggestion.confidence
        return max(0.0, round(score, 1))

    def _build_review_summary(
        self, analysis: Dict[str, Any], suggestions: List[AISuggestion]
    ) -> str:
        if not analysis:
            return "Unable to analyse file."
        lines = analysis.get("lines", 0)
        funcs = len(analysis.get("functions", []))
        classes = len(analysis.get("classes", []))
        complexity = analysis.get("complexity", 0)
        issues = len(suggestions)
        return (
            f"Analysed {lines} lines, {funcs} function(s), {classes} class(es). "
            f"Complexity: {complexity}. Found {issues} suggestion(s)."
        )

    # ------------------------------------------------------------------
    # Internal helpers — generation
    # ------------------------------------------------------------------

    def _generate_python_function(
        self,
        name: str,
        description: str,
        params: List[Dict[str, str]],
        return_type: str,
    ) -> str:
        param_str = ", ".join(
            f"{p.get('name', 'arg')}: {p.get('type', 'Any')}" for p in params
        ) or ""
        return (
            f"def {name}({param_str}) -> {return_type}:\n"
            f'    """{description}"""\n'
            f"    raise NotImplementedError\n"
        )

    def _generate_js_function(
        self,
        name: str,
        description: str,
        params: List[Dict[str, str]],
        return_type: str,
        language: str,
    ) -> str:
        param_str = ", ".join(p.get("name", "arg") for p in params)
        type_annotation = f": {return_type}" if language == "typescript" else ""
        return (
            f"/**\n * {description}\n */\n"
            f"function {name}({param_str}){type_annotation} {{\n"
            f"  throw new Error('Not implemented');\n"
            f"}}\n"
        )

    def _generate_go_function(
        self,
        name: str,
        description: str,
        params: List[Dict[str, str]],
        return_type: str,
    ) -> str:
        param_str = ", ".join(
            f"{p.get('name', 'arg')} {p.get('type', 'interface{{}}')}".replace("{{}}", "{}") for p in params
        )
        capitalized = name[0].upper() + name[1:]
        return (
            f"// {capitalized} — {description}\n"
            f"func {capitalized}({param_str}) {return_type} {{\n"
            f"\tpanic(\"not implemented\")\n"
            f"}}\n"
        )

    def _generate_python_class(
        self,
        name: str,
        description: str,
        methods: List[str],
    ) -> str:
        method_stubs = ""
        for m in methods:
            method_stubs += (
                f"\n    def {m}(self):\n"
                f'        """TODO: implement {m}."""\n'
                f"        raise NotImplementedError\n"
            )
        return (
            f"class {name}:\n"
            f'    """{description}"""\n\n'
            f"    def __init__(self) -> None:\n"
            f"        pass\n"
            f"{method_stubs}"
        )

    def _generate_pytest_suite(
        self,
        module_name: str,
        functions: List[str],
        classes: List[str],
    ) -> str:
        lines = [
            f'"""Auto-generated tests for {module_name} (Amosclaud-AI)."""\n',
            f"import pytest",
            f"from {module_name} import *\n",
        ]
        for fn in functions:
            lines.append(f"\ndef test_{fn}():")
            lines.append(f'    """Test {fn}."""')
            lines.append(f"    # TODO: implement test for {fn}")
            lines.append(f"    pass\n")
        for cls in classes:
            lines.append(f"\nclass Test{cls}:")
            lines.append(f'    """Tests for {cls}."""\n')
            lines.append(f"    def test_instantiation(self):")
            lines.append(f"        obj = {cls}()")
            lines.append(f"        assert obj is not None\n")
        return "\n".join(lines)
