#!/usr/bin/env python3
"""Deterministic failure classification for Amosclaud repair routing."""

from __future__ import annotations

from enum import Enum


class FailureClass(str, Enum):
    CODE_FAILURE = "CODE_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    LINT_FAILURE = "LINT_FAILURE"
    SECURITY_FAILURE = "SECURITY_FAILURE"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    CONFIGURATION_FAILURE = "CONFIGURATION_FAILURE"
    SECRET_MISSING = "SECRET_MISSING"
    RUNNER_FAILURE = "RUNNER_FAILURE"
    GITHUB_PROVIDER_FAILURE = "GITHUB_PROVIDER_FAILURE"
    CIRCLECI_PROVIDER_FAILURE = "CIRCLECI_PROVIDER_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    TIMEOUT = "TIMEOUT"
    NON_REPRODUCIBLE = "NON_REPRODUCIBLE"
    UNKNOWN = "UNKNOWN"


def classify_failure(
    *,
    provider: str,
    source: str = "",
    reproduced: bool | None = None,
    evidence: str = "",
) -> FailureClass:
    """Classify a failure without using a model or credentials."""
    provider_value = provider.strip().lower()
    text = f"{source}\n{evidence}".lower()

    if reproduced is False:
        if provider_value == "circleci" or "circleci" in text:
            return FailureClass.CIRCLECI_PROVIDER_FAILURE
        if provider_value in {"github", "github_actions"}:
            return FailureClass.GITHUB_PROVIDER_FAILURE
        return FailureClass.NON_REPRODUCIBLE

    if "timed out" in text or "timeout" in text:
        return FailureClass.TIMEOUT
    if any(marker in text for marker in ("connection reset", "network is unreachable", "dns", "temporary failure in name resolution")):
        return FailureClass.NETWORK_FAILURE
    if any(marker in text for marker in ("secret", "credential", "token")) and any(
        marker in text for marker in ("missing", "not configured", "required", "unauthorized", "forbidden")
    ):
        return FailureClass.SECRET_MISSING
    if any(marker in text for marker in ("runner", "executor", "machine lost", "no space left on device")):
        return FailureClass.RUNNER_FAILURE
    if any(marker in text for marker in ("codeql", "security", "vulnerability", "bandit")):
        return FailureClass.SECURITY_FAILURE
    if any(marker in text for marker in ("flake8", "ruff", "lint", "black --check", "formatting")):
        return FailureClass.LINT_FAILURE
    if any(marker in text for marker in ("dependency", "requirements", "package resolution", "no matching distribution", "npm err")):
        return FailureClass.DEPENDENCY_FAILURE
    if any(marker in text for marker in ("config", "configuration", "yaml", "toml", "environment variable")):
        return FailureClass.CONFIGURATION_FAILURE
    if any(marker in text for marker in ("pytest", "test failed", "tests failed", "assertionerror")):
        return FailureClass.TEST_FAILURE
    if any(marker in text for marker in ("syntaxerror", "traceback", "exception", "compile")):
        return FailureClass.CODE_FAILURE
    return FailureClass.UNKNOWN
