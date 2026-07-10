import os
import subprocess
import shutil
import time
import logging
from typing import Dict, Optional
from deployment_worker.config import WorkerConfig

logger = logging.getLogger("deployment-worker")

class DeploymentExecutor:
    def __init__(self, task_id: str, repo_url: str, branch: str, env_vars: Dict[str, str]):
        self.task_id = task_id
        self.repo_url = repo_url
        self.branch = branch
        self.env_vars = env_vars
        self.app_dir = os.path.abspath(os.path.join(WorkerConfig.WORKSPACE_DIR, task_id))
        self.process: Optional[subprocess.Popen] = None
        self.logs_accumulator = []

    def log(self, message: str):
        formatted = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        self.logs_accumulator.append(formatted)
        logger.info(message)

    def get_logs(self) -> str:
        return "\n".join(self.logs_accumulator)

    def clone_repo(self) -> bool:
        try:
            self.log(f"Cloning branch '{self.branch}' from {self.repo_url}...")
            if os.path.exists(self.app_dir):
                self.log(f"Cleaning up existing workspace directory: {self.app_dir}")
                shutil.rmtree(self.app_dir)
            os.makedirs(self.app_dir, exist_ok=True)
            
            cmd = ["git", "clone", "-b", self.branch, self.repo_url, self.app_dir]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            self.log("Repository cloned successfully.")
            return True
        except subprocess.CalledProcessError as e:
            self.log(f"Git clone failed: {e.stderr}")
            return False
        except Exception as e:
            self.log(f"Unexpected error during clone: {str(e)}")
            return False

    def run_build(self, build_command: str) -> bool:
        if not build_command:
            self.log("No build command specified. Skipping build stage.")
            return True
        try:
            self.log(f"Executing build command: {build_command}")
            env = {**os.environ, **self.env_vars}
            result = subprocess.run(
                build_command,
                shell=True,
                cwd=self.app_dir,
                capture_output=True,
                text=True,
                check=True,
                env=env
            )
            if result.stdout:
                self.log(f"Build stdout:\n{result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            self.log(f"Build command failed with exit code {e.returncode}")
            self.log(f"Build stderr:\n{e.stderr}")
            self.log(f"Build stdout:\n{e.stdout}")
            return False
        except Exception as e:
            self.log(f"Unexpected error during build execution: {str(e)}")
            return False

    def start_app(self, start_command: str) -> bool:
        try:
            self.log(f"Starting application with command: {start_command}")
            env = {**os.environ, **self.env_vars}
            self.process = subprocess.Popen(
                start_command,
                shell=True,
                cwd=self.app_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            time.sleep(3)
            poll_status = self.process.poll()
            if poll_status is not None:
                stdout, stderr = self.process.communicate()
                self.log(f"Application process exited immediately with code {poll_status}")
                self.log(f"Process stderr:\n{stderr}")
                return False
            self.log(f"Application running successfully. PID: {self.process.pid}")
            return True
        except Exception as e:
            self.log(f"Failed to start application: {str(e)}")
            return False

    def stop_app(self):
        if self.process and self.process.poll() is None:
            self.log(f"Stopping running process with PID: {self.process.pid}")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.log("Process stopped.")
