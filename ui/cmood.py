# File: cmood.py (Consolidated Autonomous Cloud Collector & Orchestrator)
# Tech Stack: Python, FastAPI, Uvicorn, Watchdog, Pydantic
# Description: Single-file deployment of 'cmood' (The Cloud Collector).
#              Monitors a workspace directory for "true files", clones them 
#              to a deployment workspace, and orchestrates background build/deploy workers.

import os
import sys
import time
import shutil
import queue
import logging
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# Third-Party Dependencies (Ensure these are installed: pip install fastapi uvicorn watchdog pydantic)
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ==========================================
# 1. SYSTEM CONFIGURATION
# ==========================================
class CMoodConfig:
    BASE_DIR: Path = Path(__file__).resolve().parent
    WATCH_DIRECTORY: str = os.getenv("CMOOD_WATCH_DIR", str(BASE_DIR / "workspace"))
    CLONE_DIRECTORY: str = os.getenv("CMOOD_CLONE_DIR", str(BASE_DIR / "clones"))
    
    HOST: str = os.getenv("CMOOD_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("CMOOD_PORT", "3000"))
    
    API_KEY: str = os.getenv("CMOOD_API_KEY", "cmood-super-secret-token-9988")
    MAX_WORKERS: int = int(os.getenv("CMOOD_MAX_WORKERS", "4"))
    BUILD_TIMEOUT: int = int(os.getenv("CMOOD_BUILD_TIMEOUT", "300"))

settings = CMoodConfig()

# Ensure critical directories exist immediately
Path(settings.WATCH_DIRECTORY).mkdir(parents=True, exist_ok=True)
Path(settings.CLONE_DIRECTORY).mkdir(parents=True, exist_ok=True)

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("cmood")

# ==========================================
# 2. ORCHESTRATOR & WORKER ENGINE
# ==========================================
class BuildJob:
    def __init__(self, file_path: str, action: str):
        self.job_id = f"job_{int(datetime.utcnow().timestamp())}_{os.urandom(4).hex()}"
        self.file_path = file_path
        self.action = action
        self.status = "PENDING"
        self.created_at = datetime.utcnow()
        self.completed_at: Optional[datetime] = None
        self.logs: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "file_path": self.file_path,
            "action": self.action,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "logs": self.logs
        }

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
            job = self.job_queue.get()
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
        
        source_path = Path(job.file_path)
        if not source_path.exists():
            job.status = "FAILED"
            job.logs.append(f"Source file {source_path} does not exist.")
            return

        # Resolve relative path to maintain directory structure in clone workspace
        try:
            relative_path = source_path.relative_to(Path(settings.WATCH_DIRECTORY))
        except ValueError:
            relative_path = source_path.name

        target_path = Path(settings.CLONE_DIRECTORY) / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        shutil.copy2(source_path, target_path)
        job.logs.append(f"Cloned true file to {target_path}")

        # Check for custom build script in workspace root
        build_script = Path(settings.WATCH_DIRECTORY) / "build.sh"
        if build_script.exists():
            job.logs.append("Executing custom build.sh script...")
            self._run_subprocess([str(build_script)], job)
        else:
            job.logs.append("No custom build.sh found. Running default syntax validation...")
            if source_path.suffix == ".py":
                self._run_subprocess(["python3", "-m", "py_compile", str(target_path)], job)
            else:
                job.logs.append(f"No validation defined for file extension: {source_path.suffix}")

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

# ==========================================
# 3. WATCHDOG FILE SYSTEM COLLECTOR
# ==========================================
class TrueFileCollectorHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.last_triggered: Dict[str, float] = {}
        self.debounce_interval = 1.0  # seconds

    def _should_process(self, path: str) -> bool:
        p = Path(path)
        if p.is_dir() or any(part.startswith('.') for part in p.parts):
            return False
        
        # Debounce rapid successive events for the same file
        now = time.time()
        if path in self.last_triggered:
            if now - self.last_triggered[path] < self.debounce_interval:
                return False
        self.last_triggered[path] = now
        return True

    def on_modified(self, event):
        if self._should_process(event.src_path):
            logger.info(f"File modification detected: {event.src_path}")
            orchestrator.submit_job(event.src_path, "MODIFIED")

    def on_created(self, event):
        if self._should_process(event.src_path):
            logger.info(f"File creation detected: {event.src_path}")
            orchestrator.submit_job(event.src_path, "CREATED")

class TrueFileCollector:
    def __init__(self):
        self.observer = Observer()
        self.handler = TrueFileCollectorHandler()

    def start(self):
        self.observer.schedule(self.handler, path=settings.WATCH_DIRECTORY, recursive=True)
        self.observer.start()
        logger.info(f"True File Collector started watching directory: {settings.WATCH_DIRECTORY}")

    def stop(self):
        self.observer.stop()
        self.observer.join()
        logger.info("True File Collector stopped.")

collector = TrueFileCollector()

# ==========================================
# 4. FASTAPI CONTROL PLANE
# ==========================================
app = FastAPI(
    title="cmood (The Cloud Collector)",
    description="Autonomous file collection and build/deploy orchestration engine.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return x_api_key

@app.on_event("startup")
def startup_event():
    orchestrator.start()
    collector.start()

@app.on_event("shutdown")
def shutdown_event():
    collector.stop()
    orchestrator.stop()

@app.get("/status", tags=["System"])
def get_status():
    return {
        "status": "ONLINE",
        "watch_directory": settings.WATCH_DIRECTORY,
        "clone_directory": settings.CLONE_DIRECTORY,
        "active_workers": len(orchestrator.active_workers),
        "pending_jobs": orchestrator.job_queue.qsize()
    }

@app.get("/jobs", response_model=List[Dict[str, Any]], tags=["Jobs"])
def list_jobs(api_key: str = Depends(verify_api_key)):
    return [job.to_dict() for job in orchestrator.jobs.values()]

@app.get("/jobs/{job_id}", tags=["Jobs"])
def get_job_details(job_id: str, api_key: str = Depends(verify_api_key)):
    job = orchestrator.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()

class SyncRequest(BaseModel):
    file_path: str

@app.post("/sync", tags=["System"])
def trigger_manual_sync(payload: SyncRequest, api_key: str = Depends(verify_api_key)):
    target_path = Path(payload.file_path)
    if not target_path.exists():
        raise HTTPException(status_code=400, detail="Target file path does not exist on host.")
    
    job_id = orchestrator.submit_job(str(target_path), "MANUAL_SYNC")
    return {"status": "SUBMITTED", "job_id": job_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)

