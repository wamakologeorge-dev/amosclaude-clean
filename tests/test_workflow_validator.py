"""Tests for the Amosclaud-native GitHub Actions workflow validator."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from amosclaud_bot.workflow_validator import (
    Finding,
    contexts_in,
    validate_directory,
    validate_text,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def codes(findings: list[Finding]) -> set[str]:
    return {finding.code for finding in findings}


def test_valid_workflow_is_accepted() -> None:
    text = textwrap.dedent("""
        name: Example
        on:
          pull_request:
        jobs:
          build:
            runs-on: ubuntu-latest
            env:
              GREETING: ${{ github.actor }}
            steps:
              - run: echo "$GREETING"
        """)
    assert validate_text(text, "example.yml") == []


def test_workflow_listening_to_itself_is_rejected() -> None:
    """Regression: this single line disabled the repair control plane."""

    text = textwrap.dedent("""
        name: Amosclaud Repair Control Plane
        on:
          workflow_run:
            workflows:
              - CodeQL
              - Amosclaud Repair Control Plane
            types: [completed]
        jobs:
          repair:
            runs-on: ubuntu-latest
            steps:
              - run: echo repair
        """)
    findings = validate_text(text, "repair.yml")
    assert codes(findings) == {"AWV003"}
    assert "cannot listen to itself" in findings[0].message


def test_workflow_listening_to_other_workflows_is_accepted() -> None:
    text = textwrap.dedent("""
        name: Amosclaud Repair Control Plane
        on:
          workflow_run:
            workflows: [CodeQL, Fortify AST Scan]
            types: [completed]
        jobs:
          repair:
            runs-on: ubuntu-latest
            steps:
              - run: echo repair
        """)
    assert validate_text(text, "repair.yml") == []


def test_runner_context_in_job_env_is_rejected() -> None:
    """Regression: four workflows died on this exact pattern."""

    text = textwrap.dedent("""
        name: Scan
        on: [push]
        jobs:
          scan:
            runs-on: ubuntu-latest
            env:
              SCAN_DIR: ${{ runner.temp }}/amosclaud-scan
            steps:
              - run: echo "$SCAN_DIR"
        """)
    findings = validate_text(text, "scan.yml")
    assert codes(findings) == {"AWV004"}
    assert "runner" in findings[0].message


def test_runner_context_in_step_env_is_accepted() -> None:
    """The same context is legal one level down; the validator must not overreach."""

    text = textwrap.dedent("""
        name: Scan
        on: [push]
        jobs:
          scan:
            runs-on: ubuntu-latest
            steps:
              - env:
                  SCAN_DIR: ${{ runner.temp }}/amosclaud-scan
                run: echo "$SCAN_DIR"
        """)
    assert validate_text(text, "scan.yml") == []


def test_runner_context_in_workflow_env_is_rejected() -> None:
    text = textwrap.dedent("""
        name: Scan
        on: [push]
        env:
          SCAN_DIR: ${{ runner.temp }}/x
        jobs:
          scan:
            runs-on: ubuntu-latest
            steps:
              - run: echo ok
        """)
    assert codes(validate_text(text, "scan.yml")) == {"AWV004"}


def test_secrets_are_allowed_in_job_env_but_not_job_if() -> None:
    allowed = textwrap.dedent("""
        name: Deploy
        on: [push]
        jobs:
          deploy:
            runs-on: ubuntu-latest
            env:
              TOKEN: ${{ secrets.GITHUB_TOKEN }}
            steps:
              - run: echo ok
        """)
    assert validate_text(allowed, "deploy.yml") == []

    rejected = textwrap.dedent("""
        name: Deploy
        on: [push]
        jobs:
          deploy:
            runs-on: ubuntu-latest
            if: ${{ steps.previous.outputs.ready }}
            steps:
              - run: echo ok
        """)
    assert codes(validate_text(rejected, "deploy.yml")) == {"AWV004"}


def test_function_calls_are_not_mistaken_for_contexts() -> None:
    text = textwrap.dedent("""
        name: Example
        on: [push]
        jobs:
          build:
            runs-on: ubuntu-latest
            env:
              KEY: ${{ hashFiles('**/lock') }}-${{ fromJSON('{"a":1}').a }}
            steps:
              - run: echo ok
        """)
    assert validate_text(text, "example.yml") == []


def test_conda_environment_file_is_reported_as_not_a_workflow() -> None:
    text = textwrap.dedent("""
        name: amosclaud
        channels:
          - defaults
        dependencies:
          - python=3.12
        """)
    findings = validate_text(text, "environment.yml")
    assert codes(findings) == {"AWV002"}
    assert "conda" in findings[0].message


def test_missing_trigger_is_reported() -> None:
    text = textwrap.dedent("""
        name: Example
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - run: echo ok
        """)
    assert "AWV006" in codes(validate_text(text, "example.yml"))


def test_yaml_syntax_error_is_reported_with_a_line() -> None:
    findings = validate_text("name: Example\non: [push\njobs: {}\n", "broken.yml")
    assert codes(findings) == {"AWV001"}
    assert findings[0].line >= 1


def test_caller_of_a_broken_workflow_is_reported(tmp_path: Path) -> None:
    """Regression: main.yml and results.yml died only because agent-chat.yml did."""

    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "agent-chat.yml").write_text(
        textwrap.dedent("""
            name: Agent Chat
            on:
              workflow_call:
            jobs:
              doctor:
                runs-on: ubuntu-latest
                env:
                  REPORT_PATH: ${{ runner.temp }}/report.json
                steps:
                  - run: echo ok
            """),
        encoding="utf-8",
    )
    (directory / "main.yml").write_text(
        textwrap.dedent("""
            name: Main
            on: [push]
            jobs:
              call:
                uses: ./.github/workflows/agent-chat.yml
            """),
        encoding="utf-8",
    )

    findings = validate_directory(tmp_path)
    by_path = {finding.path: finding.code for finding in findings}
    assert by_path[".github/workflows/agent-chat.yml"] == "AWV004"
    assert by_path[".github/workflows/main.yml"] == "AWV005"


def test_contexts_in_extracts_roots() -> None:
    assert contexts_in("${{ runner.temp }}/x") == {"runner"}
    assert contexts_in("plain text") == set()
    assert contexts_in("${{ github.event.issue.number }}") == {"github"}


def test_repository_workflows_are_all_valid() -> None:
    """Every workflow in this repository must be one GitHub can actually load."""

    findings = validate_directory(REPO_ROOT)
    assert findings == [], "\n".join(finding.format() for finding in findings)


def test_guard_runs_without_the_full_runtime_dependency_set(tmp_path):
    """The guard must import under the fast lane's minimal dependencies.

    The fast pull-request lane installs ``requirements-ci-fast.txt`` -- a
    formatter, pytest, PyYAML and websockets. It does not install FastAPI. An
    earlier version of this guard imported ``amosclaud_bot.workflow_validator``
    through the package, which executes ``amosclaud_bot/__init__.py`` and pulls
    in the whole bot and FastAPI. It passed every local check only because the
    development machine happened to have FastAPI installed.

    This test denies the guard the heavy dependencies and insists it still runs.
    """
    shim = tmp_path / "shim"
    shim.mkdir()
    for blocked in ("fastapi", "starlette", "pydantic", "uvicorn"):
        (shim / f"{blocked}.py").write_text(
            f'raise ImportError("{blocked} is not available in the fast lane")\n',
            encoding="utf-8",
        )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim)
    guard = REPO_ROOT / "scripts" / "ci" / "workflow_validator_guard.py"
    clean = tmp_path / "clean"
    (clean / ".github" / "workflows").mkdir(parents=True)
    (clean / ".github" / "workflows" / "ok.yml").write_text(
        "name: Ok\non:\n  push:\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo hi\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(guard), "--root", str(clean)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert "ImportError" not in result.stderr, result.stderr
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
