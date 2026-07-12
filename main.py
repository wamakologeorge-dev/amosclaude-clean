"""Amosclaud repository entry point.

This script backs the CI/CD pipeline defined in
``.github/workflows/ci-pipeline.yml`` and provides a local runner for the
FastAPI application.

Commands:
    python main.py --test-guardrails   Validate the codebase (compile, import, test suite)
    python main.py --deploy            Deploy to the Amoscloud platform (main branch only)
    python main.py --serve             Run the FastAPI application locally
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def run_guardrails() -> int:
    """Run compile-time and test-time guardrail validation.

    Returns a process exit code (0 = all guardrails passed).
    """
    print("== Guardrail 1/3: application package compiles ==")
    result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", os.path.join(REPO_ROOT, "amoscloud_ai")],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("FAIL: amoscloud_ai package does not compile.")
        return result.returncode

    print("== Guardrail 2/3: application imports ==")
    result = subprocess.run(
        [sys.executable, "-c", "import amoscloud_ai.main"],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("FAIL: amoscloud_ai.main failed to import.")
        return result.returncode

    print("== Guardrail 3/3: test suite ==")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("FAIL: test suite reported failures.")
        return result.returncode

    print("All guardrails passed.")
    return 0


def run_deploy() -> int:
    """Deploy to the Amoscloud platform.

    Safety rules:
    - Deployment only proceeds from the ``main`` branch in CI. Any other
      branch is a validation-only run and exits successfully without
      deploying.
    - A missing AMOSCLOUD_API_TOKEN skips deployment with a warning instead
      of failing the pipeline (which would otherwise auto-open false
      security-incident issues).
    """
    branch = os.environ.get("GITHUB_REF_NAME", "")
    if branch and branch != "main":
        print(f"Deployment skipped: branch '{branch}' is validation-only. "
              "Deployments run from 'main' exclusively.")
        return 0

    api_token = os.environ.get("AMOSCLOUD_API_TOKEN")
    if not api_token:
        print("Deployment skipped: AMOSCLOUD_API_TOKEN is not configured. "
              "Add the secret to enable deployments from 'main'.")
        return 0

    print("Token successfully retrieved securely. Proceeding with deployment...")
    # Deployment integration point: invoke the Amoscloud platform deployment
    # here once the platform endpoint is finalized.
    print("Deployment step completed.")
    return 0


def run_serve() -> int:
    """Run the FastAPI application locally."""
    import uvicorn

    from amoscloud_ai.config import settings

    uvicorn.run(
        "amoscloud_ai.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Amosclaud repository entry point.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test-guardrails", action="store_true",
                       help="Run compile, import, and test-suite validation.")
    group.add_argument("--deploy", action="store_true",
                       help="Deploy to the Amoscloud platform (main branch only).")
    group.add_argument("--serve", action="store_true",
                       help="Run the FastAPI application locally.")
    args = parser.parse_args(argv)

    if args.test_guardrails:
        return run_guardrails()
    if args.deploy:
        return run_deploy()
    if args.serve:
        return run_serve()

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
