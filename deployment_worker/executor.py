import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict

from amoscloud_ai.isolated_runner import (
    RunnerConfigurationError,
    UnsafeCommandError,
    run_in_isolated_container,
)
from deployment_worker.config import WorkerConfig


logger = logging.getLogger("deployment-worker")


class DeploymentExecutor:
    """Deployment worker that never executes user commands on the host shell."""

    def __init__(
        self,
        task_id: str,
        repo_url: str,
        branch: str,
        env_vars: Dict[str, str],
    ):
        self.task_id = task_id
        self.repo_url = repo_url
        self.branch = branch
        self.env_vars = env_vars
        self.app_dir = os.path.abspath(
            os.path.join(WorkerConfig.WORKSPACE_DIR, task_id)
        )
        self.logs_accumulator: list[str] = []

    def log(self, message: str) -> None:
        formatted = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        self.logs_accumulator.append(formatted)
        logger.info(message)

    def get_logs(self) -> str:
        return "\n".join(self.logs_accumulator)

    def clone_repo(self) -> bool:
        try:
            self.log(f"Cloning branch '{self.branch}' from the configured repository.")
            if os.path.exists(self.app_dir):
                self.log("Cleaning the existing isolated workspace.")
                shutil.rmtree(self.app_dir)
            os.makedirs(self.app_dir, exist_ok=True)

            command = [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                "--branch",
                self.branch,
                self.repo_url,
                self.app_dir,
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=180,
            )
            if result.stdout:
                self.log(result.stdout[-4_000:])
            self.log("Repository cloned successfully.")
            return True
        except subprocess.CalledProcessError as exc:
            self.log(f"Git clone failed with exit code {exc.returncode}.")
            return False
        except subprocess.TimeoutExpired:
            self.log("Git clone timed out.")
            return False
        except Exception as exc:
            self.log(f"Repository clone stopped safely: {type(exc).__name__}.")
            return False

    def run_build(self, build_command: str) -> bool:
        if not build_command:
            self.log("No build command specified. Skipping build stage.")
            return True
        try:
            self.log("Executing the build in an isolated runner container.")
            result = run_in_isolated_container(
                build_command,
                workspace=Path(self.app_dir),
                environment=self.env_vars,
                timeout_seconds=int(
                    os.getenv("AMOSCLAUD_DEPLOY_BUILD_TIMEOUT_SECONDS", "900")
                ),
            )
            if result.output:
                self.log(result.output)
            if result.returncode != 0:
                self.log(
                    f"Isolated build failed with exit code {result.returncode}."
                )
                return False
            return True
        except (RunnerConfigurationError, UnsafeCommandError) as exc:
            self.log(f"Build blocked by runner policy: {exc}")
            return False
        except Exception as exc:
            self.log(f"Isolated build stopped safely: {type(exc).__name__}.")
            return False

    def start_app(self, start_command: str) -> bool:
        """Refuse to host generated applications inside the deployment worker.

        Production previews must be published to the dedicated preview service.
        Keeping this method provides a truthful compatibility result to legacy
        callers without reintroducing host command execution.
        """

        del start_command
        self.log(
            "Application start was not executed. Publish the verified artifact "
            "to the dedicated Amosclaud preview service instead."
        )
        return False

    def stop_app(self) -> None:
        self.log("No in-process application is running; no stop action is required.")
