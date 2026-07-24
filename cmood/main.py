# cmood/main.py
import os
import shutil
import time
from pathlib import Path
from datetime import datetime
import asyncio
from threading import Thread # Used for running watchdog in a separate thread
from dotenv import load_dotenv

from fastapi import FastAPI, BackgroundTasks
import uvicorn
from pydantic import BaseModel

# For file system monitoring
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Configuration Loading ---
load_dotenv() # Load environment variables from .env file

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Amosclaud cmood Autonomous Agent & API",
    description="The Cloud Collector: Collects, clones, and orchestrates deployments autonomously.",
    version="1.0.0"
)

# --- Cmood Agent Core Logic ---
class CmoodAgentCore:
    """
    The heart of cmood: handles file collection, cloning, and orchestration.
    Runs as an autonomous agent, monitoring for new files and processing them.
    """
    def __init__(self, repo_name: str = "wamakologeorge-dev/amosclaud", base_dir: Path = Path(__file__).parent):
        self.repo_name = repo_name
        self.base_dir = base_dir.resolve()
        self.collection_dir = self.base_dir / "collected_files"
        self.clone_dir = self.base_dir / "cloud_clones"
        
        # Ensure directories exist
        self.collection_dir.mkdir(exist_ok=True)
        self.clone_dir.mkdir(exist_ok=True)
        
        print(f"Amosclaud cmood Agent Core initialized for repo: {self.repo_name}")
        print(f"Collection directory: {self.collection_dir}")
        print(f"Clone directory: {self.clone_dir}")
        
        self.is_watching = False
        self.observer = None
        self.loop = asyncio.get_event_loop() # Get the event loop for async tasks

    def _notify_cloud(self, file_path: Path, status: str, message: str):
        """
        Simulates notifying a cloud service (e.g., GitHub Status API, Vercel deployment status).
        This is where cmood connects to the 'cloud serve true'.
        """
        print(f"[Cloud Notification] File: {file_path.name}, Status: {status}, Message: {message}")
        # In a real scenario, this would make an HTTP request to a cloud provider's API.
        # Example:
        # github_token = os.getenv("GITHUB_TOKEN")
        # if github_token:
        #     headers = {"Authorization": f"token {github_token}"}
        #     payload = {"state": status, "description": message, "context": "cmood/agent"}
        #     requests.post(f"https://api.github.com/repos/{self.repo_name}/statuses/{os.getenv('GITHUB_SHA')}", json=payload, headers=headers)
        print("Agent huh take cmood you came with this is in white t shirt party ai agent hi I see it I forgot I'm")

    def collect_file(self, source_path: Path) -> Path | None:
        """
        Collects a 'true file' or 'pass file' into the collection directory.
        cmood collect data name file.
        """
        if not source_path.exists():
            print(f"Error: Source file not found at {source_path}")
            self._notify_cloud(source_path, "error", f"Source file '{source_path.name}' not found for collection.")
            return None
        
        collected_path = self.collection_dir / source_path.name
        try:
            shutil.copy2(source_path, collected_path)
            print(f"Collected true file: {source_path.name} -> {collected_path}")
            self._notify_cloud(collected_path, "collected", f"File '{source_path.name}' collected by cmood.")
            return collected_path
        except Exception as e:
            print(f"Error collecting file {source_path.name}: {e}")
            self._notify_cloud(source_path, "error", f"Error collecting file '{source_path.name}': {e}")
            return None

    def clone_file(self, collected_path: Path) -> Path | None:
        """
        Creates a 'cloud clone' of the collected file.
        cmood clone.
        """
        if not collected_path.exists():
            print(f"Error: Collected file not found at {collected_path}")
            self._notify_cloud(collected_path, "error", f"Collected file '{collected_path.name}' not found for cloning.")
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        clone_name = f"{collected_path.stem}_clone_{timestamp}{collected_path.suffix}"
        cloned_path = self.clone_dir / clone_name
        try:
            shutil.copy2(collected_path, cloned_path)
            print(f"Cloned file: {collected_path.name} -> {cloned_path}")
            self._notify_cloud(cloned_path, "cloned", f"File '{collected_path.name}' cloned by cmood.")
            return cloned_path
        except Exception as e:
            print(f"Error cloning file {collected_path.name}: {e}")
            self._notify_cloud(collected_path, "error", f"Error cloning file '{collected_path.name}': {e}")
            return None

    async def orchestrate_build_and_deploy(self, cloned_file_path: Path):
        """
        Triggers build-worker and deployment-worker.
        This is where cmood takes over from creating branches.
        """
        if not cloned_file_path:
            print("No cloned file to orchestrate build/deploy.")
            self._notify_cloud(Path("N/A"), "skipped", "Orchestration skipped: no cloned file.")
            return

        print(f"Orchestrating build for {cloned_file_path.name}...")
        # In a real system, this would make an async API call to the build-worker service
        # Example:
        # build_worker_url = os.getenv('BUILD_WORKER_URL')
        # if build_worker_url:
        #     async with httpx.AsyncClient() as client:
        #         await client.post(f"{build_worker_url}/build", json={"file": str(cloned_file_path)})
        await asyncio.sleep(1) # Simulate async work
        print("cmood build-worker triggered.")
        self._notify_cloud(cloned_file_path, "building", f"Build triggered for '{cloned_file_path.name}'.")
        
        print(f"Orchestrating deployment for {cloned_file_path.name}...")
        # Example:
        # deployment_worker_url = os.getenv('DEPLOYMENT_WORKER_URL')
        # if deployment_worker_url:
        #     async with httpx.AsyncClient() as client:
        #         await client.post(f"{deployment_worker_url}/deploy", json={"file": str(cloned_file_path)})
        await asyncio.sleep(1) # Simulate async work
        print("cmood deployment-worker triggered. TASK COMPLETE.")
        self._notify_cloud(cloned_file_path, "deployed", f"File '{cloned_file_path.name}' deployed by cmood.")

    async def process_file_autonomously(self, file_path: Path):
        """
        Full autonomous processing pipeline for a single file.
        cmood mood agent is working.
        """
        print(f"\n[cmood Agent] Processing new file: {file_path.name}")
        self._notify_cloud(file_path, "processing", f"File '{file_path.name}' detected and processing started.")
        
        collected = self.collect_file(file_path)
        if collected:
            cloned = self.clone_file(collected)
            if cloned:
                await self.orchestrate_build_and_deploy(cloned)
        print(f"[cmood Agent] Finished processing {file_path.name}")
        self._notify_cloud(file_path, "completed", f"Processing of '{file_path.name}' completed by cmood.")

    def _run_watchdog_blocking(self, watch_path: Path):
        """
        Blocking function to run watchdog observer in a separate thread.
        This allows FastAPI to run on the main thread while watchdog monitors.
        """
        print(f"cmood agent starting watchdog on: {watch_path} (in background thread)")
        event_handler = CmoodEventHandler(self.process_file_autonomously_sync_wrapper)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(watch_path), recursive=False)
        self.observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Watchdog received KeyboardInterrupt.")
        finally:
            self.observer.stop()
            self.observer.join()
            print("cmood agent watchdog thread stopped.")

    def process_file_autonomously_sync_wrapper(self, file_path: Path):
        """
        Wrapper to call the async processing function from the sync watchdog event handler.
        This ensures async tasks are run on the main event loop.
        """
        # Schedule the async task to run on the main event loop
        asyncio.run_coroutine_threadsafe(self.process_file_autonomously(file_path), self.loop)

    def start_watchdog_in_thread(self, watch_path: Path):
        """Starts the watchdog observer in a new daemon thread."""
        if self.is_watching:
            print("Watchdog is already running.")
            return
        
        self.is_watching = True
        watch_thread = Thread(target=self._run_watchdog_blocking, args=(watch_path,))
        watch_thread.daemon = True # Allows main program to exit even if thread is running
        watch_thread.start()
        print(f"Watchdog thread started for path: {watch_path}")

    def stop_watchdog(self):
        """Stops the watchdog observer."""
        if self.observer and self.is_watching:
            self.observer.stop()
            self.observer.join()
            self.is_watching = False
            print("Watchdog stopped.")

class CmoodEventHandler(FileSystemEventHandler):
    """Custom event handler for watchdog to process new file creation."""
    def __init__(self, callback_function):
        self.callback = callback_function

    def on_created(self, event):
        if not event.is_directory:
            print(f"Detected new file via watchdog: {event.src_path}")
            self.callback(Path(event.src_path))

# --- Global Cmood Agent Instance ---
cmood_agent = CmoodAgentCore()

# --- FastAPI Event Hooks ---
@app.on_event("startup")
async def startup_event():
    """Executed when the FastAPI application starts up."""
    print("cmood start job output should show running...")
    
    # Ensure the input directory for watchdog exists
    watch_path_str = os.getenv("CMOOD_WATCH_PATH", str(cmood_agent.base_dir / "input_files"))
    watch_path = Path(watch_path_str)
    watch_path.mkdir(parents=True, exist_ok=True) # Ensure watch directory exists
    
    # Store the event loop for later use by the watchdog thread
    cmood_agent.loop = asyncio.get_event_loop() 
    
    cmood_agent.start_watchdog_in_thread(watch_path)
    print("cmood ci clone cmood cloud clone cmood mood agent is working cmood wait arguments with agent...")
    print(f"Monitoring for new files in: {watch_path}")

@app.on_event("shutdown")
async def shutdown_event():
    """Executed when the FastAPI application shuts down."""
    cmood_agent.stop_watchdog()
    print("cmood agent shut down gracefully.")

# --- FastAPI Endpoints ---
class ProcessFileRequest(BaseModel):
    file_path: str

@app.get("/status")
async def get_status():
    """Returns the current status of the cmood agent."""
    return {
        "status": "running",
        "agent_watching": cmood_agent.is_watching,
        "collection_dir": str(cmood_agent.collection_dir),
        "clone_dir": str(cmood_agent.clone_dir),
        "message": "cmood auto Amosclaud agent auto integration cloud serve true"
    }

@app.post("/process_file")
async def process_file_api(request: ProcessFileRequest, background_tasks: BackgroundTasks):
    """
    API endpoint to manually trigger file processing.
    The file should exist relative to the cmood base directory or be an absolute path.
    """
    target_file_path = Path(request.file_path)
    if not target_file_path.is_absolute():
        target_file_path = cmood_agent.base_dir / target_file_path

    if not target_file_path.exists():
        return {"message": f"Error: File not found at {target_file_path}", "status": "failed"}
    
    # Run the processing in a background task to not block the API response
    background_tasks.add_task(cmood_agent.process_file_autonomously, target_file_path)
    return {"message": f"Processing of file '{target_file_path.name}' initiated in background.", "status": "processing"}

# --- Main execution block for Uvicorn ---
if __name__ == "__main__":
    # Ensure the input_files directory exists for watchdog to monitor
    # This is also handled in startup_event, but good for direct script execution clarity
    input_files_path = cmood_agent.base_dir / "input_files"
    input_files_path.mkdir(exist_ok=True)
    print(f"Create files in '{input_files_path}' to trigger cmood agent via watchdog.")
    
    uvicorn.run(
        app, 
        host=os.getenv("CMOOD_HOST", "0.0.0.0"), 
        port=int(os.getenv("CMOOD_PORT", 8000))
    )

