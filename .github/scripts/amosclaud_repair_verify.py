#!/usr/bin/env python3
"""Run credential-free, check-specific verification for Amosclaud repairs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

SENSITIVE_ENV_PARTS = (
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "API_KEY",
    "PRIVATE_KEY",
    "CREDENTIAL",
)


@dataclass
class Result:
    name: str
    command: list[str]
    returncode: int
    output: str
    skipped: bool = False


def sanitized_environment() -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper in {"GITHUB_TOKEN", "GH_TOKEN", "CIRCLECI_TOKEN", "AMOSCLAUD_AUTONOMOUS_TOKEN"}:
            continue
        if any(part in upper for part in SENSITIVE_ENV_PARTS):
            continue
        clean[key] = value
    clean["PYTHONDONTWRITEBYTECODE"] = "1"
    clean["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    clean["CI"] = "true"
    return clean


def run_step(name: str, command: list[str], cwd: Path, env: dict[str, str], timeout: int = 1200) -> Result:
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return Result(name, command, process.returncode, process.stdout)
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or "") + f"\nTimed out after {timeout} seconds."
        return Result(name, command, 124, output)


def existing(paths: Iterable[Path]) -> list[str]:
    return [str(path) for path in paths if path.is_file()]


def load_changed_files(args: argparse.Namespace) -> list[str]:
    if args.candidate_report:
        report = json.loads(Path(args.candidate_report).read_text(encoding="utf-8"))
        return [str(item) for item in report.get("changed_files", []) if isinstance(item, str)]
    if args.changed_files_json:
        value = json.loads(args.changed_files_json)
        return [str(item) for item in value if isinstance(item, str)]
    return []


def build_plan(target: Path, python: str, source: str, changed_files: list[str]) -> list[tuple[str, list[str], int]]:
    lower_source = source.lower()
    changed_lower = [item.lower() for item in changed_files]
    plan: list[tuple[str, list[str], int]] = [
        (
            "editable_install",
            [python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "-e", "."],
            1200,
        ),
        (
            "flake8_critical",
            [python, "-m", "flake8", ".", "--count", "--select=E9,F63,F7,F82", "--show-source", "--statistics"],
            900,
        ),
        (
            "python_compileall",
            [python, "-m", "compileall", "-q", "amoscloud_ai", "src", "tests"],
            900,
        ),
        (
            "pytest_full",
            [python, "-m", "pytest", "-q", "--disable-warnings", "--maxfail=25"],
            1800,
        ),
    ]

    js_files = [target / item for item in changed_files if item.lower().endswith((".js", ".mjs", ".cjs"))]
    if js_files and shutil.which("node"):
        for path in js_files:
            if path.is_file():
                plan.append((f"node_check:{path.relative_to(target)}", ["node", "--check", str(path)], 300))

    workflow_signal = "workflow" in lower_source or any(item.startswith(".github/") for item in changed_lower)
    if workflow_signal:
        workflow_tests = existing(sorted((target / "tests").glob("test_*workflow*contract.py")))
        workflow_tests += existing(sorted((target / "tests").glob("test_*github_actions*.py")))
        if workflow_tests:
            plan.append(("pytest_workflow_contracts", [python, "-m", "pytest", "-q", *workflow_tests], 1200))

    pages_signal = "pages" in lower_source or any("pages" in item for item in changed_lower)
    pages_tests = existing(
        [
            target / "tests" / "test_github_pages_deployment_contract.py",
            target / "tests" / "test_pages_site_contract.py",
        ]
    )
    if pages_signal and pages_tests:
        plan.append(("pytest_pages_contracts", [python, "-m", "pytest", "-q", *pages_tests], 900))

    api_signal = any(token in lower_source for token in ("live server", "api", "endpoint", "server check"))
    api_tests = existing(
        [
            target / "tests" / "test_build_endpoints.py",
            target / "tests" / "test_api_endpoints.py",
            target / "tests" / "test_live_server_contract.py",
        ]
    )
    if api_signal and api_tests:
        plan.append(("pytest_api_smoke_contracts", [python, "-m", "pytest", "-q", *api_tests], 1200))

    docker_signal = "docker" in lower_source or any(item == "dockerfile" or item.startswith("docker/") for item in changed_lower)
    if docker_signal and (target / "Dockerfile").is_file() and shutil.which("docker"):
        plan.append(("docker_build", ["docker", "build", "--pull=false", "-t", "amosclaud-repair-verify", "."], 1800))

    return plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--failure-source", default="")
    parser.add_argument("--changed-files-json", default="")
    parser.add_argument("--candidate-report", default="")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    target = Path(args.target).resolve()
    changed_files = load_changed_files(args)
    env = sanitized_environment()
    python = sys.executable
    results: list[Result] = []

    for name, command, timeout in build_plan(target, python, args.failure_source, changed_files):
        result = run_step(name, command, target, env, timeout)
        results.append(result)
        print(f"\n=== {name} ===")
        print("$ " + " ".join(command))
        print(result.output)
        if result.returncode != 0:
            break

    passed = bool(results) and all(item.returncode == 0 for item in results)
    Path(args.report).write_text(
        json.dumps(
            {
                "status": "passed" if passed else "failed",
                "credential_free": True,
                "failure_source": args.failure_source,
                "changed_files": changed_files,
                "results": [asdict(item) for item in results],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"AMOSCLAUD_VERIFICATION_PASSED={'true' if passed else 'false'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
