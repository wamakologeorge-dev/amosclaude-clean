import os
import shutil
import subprocess
import threading
import queue
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
from cmood.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cmood.orchestrator")

class BuildJob:
    def __init__(self, file_path: str, action: str):
        self.job_id = f"job_{int(datetime.utcnow().timestamp())}"
        self.file_path = file_path
        self.action = action
        self.status = "PENDING"
        self.created_at = datetime.utcnow()
        self.completed_at = None
        self.logs: List[str] = []

class DeploymentOrchestrator:
    def __init__(self):
        self.job_queue: queue.Queue = queue.Queue()
        self.jobs: Dict[str, BuildJob] = {}
        self.active_workers: List[threading.Thread] = []
        self.running = False

    def start(self):
        self.running = True
        for i in range(settings.MAX_WORKERS):
            t = threading.Thread(target=self._worker_loop, name=f"cmood-worker-{i}", daemon=True)
            t.start()
            self.active_workers.append(t)
        logger.info(f"Orchestrator started with {settings.MAX_WORKERS} background workers.")

    def stop(self):
        self.running = False
        # Feed poison pills to workers
        for _ in range(settings.MAX_WORKERS):
            self.job_queue.put(None)
        for t in self.active_workers:
            t.join(timeout=5)
        logger.info("Orchestrator stopped.")

    def submit_job(self, file_path: str, action: str) -> str:
        job = BuildJob(file_path, action)
        self.jobs[job.job_id] = job
        self.job_queue.put(job)
        logger.info(f"Submitted job {job.job_id} for file {file_path} ({action})")
        return job.job_id

    def _worker_loop(self):
        while self.running:
            job: BuildJob = self.job_queue.get()
            if job is None:
                self.job_queue.task_done()
                break
            
            try:
                self._execute_job(job)
            except Exception as e:
                job.status = "FAILED"
                job.logs.append(f"Execution failed: {str(e)}")
                logger.error(f"Job {job.job_id} failed: {str(e)}")
            finally:
                job.completed_at = datetime.utcnow()
                self.job_queue.task_done()

    def _execute_job(self, job: BuildJob):
        job.status = "RUNNING"
        job.logs.append(f"Starting job {job.job_id} at {datetime.utcnow()}")
        
        # 1. Clone the "true file" state to the clone workspace
        source_path = Path(job.file_path)
        if not source_path.exists():
            job.status = "FAILED"
            job.logs.append(f"Source file {source_path} does not exist.")
            return

        relative_path = source_path.relative_to(Path(settings.WATCH_DIRECTORY))
        target_path = Path(settings.CLONE_DIRECTORY) / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(source_path, target_path)
        job.logs.append(f"Cloned true file to {target_path}")

        # 2. Orchestrate Build/Deploy Worker Execution
        # If a Dockerfile or deployment script is present in the workspace, execute it
        build_script = Path(settings.WATCH_DIRECTORY) / "build.sh"
        if build_script.exists():
            job.logs.append("Executing build.sh script...")
            self._run_subprocess([str(build_script)], job)
        else:
            # Default fallback: Simulate container build or direct deployment command
            job.logs.append("No custom build.sh found. Running default validation build...")
            self._run_subprocess(["python3", "-m", "py_compile", str(target_path)], job)

        if job.status != "FAILED":
            job.status = "SUCCESS"
            job.logs.append(f"Job completed successfully at {datetime.utcnow()}")

    def _run_subprocess(self, command: List[str], job: BuildJob):
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=settings.WATCH_DIRECTORY
            )
            stdout, stderr = process.communicate(timeout=settings.BUILD_TIMEOUT)
            
            if stdout:
                job.logs.append(f"[STDOUT]\n{stdout}")
            if stderr:
                job.logs.append(f"[STDERR]\n{stderr}")
                
            if process.returncode != 0:
                job.status = "FAILED"
                job.logs.append(f"Process exited with non-zero code: {process.returncode}")
            else:
                job.logs.append("Process executed successfully.")
        except subprocess.TimeoutExpired:
            process.kill()
            job.status = "FAILED"
            job.logs.append(f"Process timed out after {settings.BUILD_TIMEOUT} seconds.")
        except Exception as e:
            job.status = "FAILED"
            job.logs.append(f"Subprocess execution error: {str(e)}")

orchestrator = DeploymentOrchestrator()
