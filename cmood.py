# cmood.py
import os
import threading
import time
from datetime import datetime
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from uvicorn import Config, Server
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Global State for cmood Agent ---
class CMoodState:
    def __init__(self):
        self.ci_clone_status: str = "Initializing..."
        self.cloud_clone_status: str = "Initializing..."
        self.mood_agent_status: str = "Initializing..."
        self.wait_arguments_status: str = "Initializing..."
        self.watched_directory: str = "/app/watched_files" # As per image
        self.last_event: Dict[str, Any] = {
            "type": "None",
            "path": "N/A",
            "timestamp": "N/A"
        }
        self.logs: List[str] = []
        self.log_lock = threading.Lock() # For thread-safe logging

    def add_log(self, message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.log_lock:
            self.logs.append(f"{timestamp} - {message}")
            # Keep logs to a reasonable size (e.g., last 100 messages)
            if len(self.logs) > 100:
                self.logs = self.logs[-100:]

    def update_agent_status(self, ci: str = None, cloud: str = None, mood: str = None, wait: str = None):
        if ci: self.ci_clone_status = ci
        if cloud: self.cloud_clone_status = cloud
        if mood: self.mood_agent_status = mood
        if wait: self.wait_arguments_status = wait
        self.add_log(f"Agent status updated: CI={self.ci_clone_status}, Cloud={self.cloud_clone_status}, Mood={self.mood_agent_status}, Wait={self.wait_arguments_status}")

    def update_file_event(self, event_type: str, path: str):
        self.last_event = {
            "type": event_type,
            "path": path,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.add_log(f"File system event: {event_type} - {path}")

cmood_state = CMoodState()

# --- Watchdog Event Handler ---
class CMoodFileSystemEventHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            cmood_state.update_file_event("File created", event.src_path)
            cmood_state.add_log(f"Cloud clone initiated for {os.path.basename(event.src_path)}")

    def on_deleted(self, event):
        if not event.is_directory:
            cmood_state.update_file_event("File deleted", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            cmood_state.update_file_event("File modified", event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            cmood_state.update_file_event("File moved", f"from {event.src_path} to {event.dest_path}")

# --- FastAPI Application ---
app = FastAPI(
    title="cmood Cloud Collector Dashboard",
    description="Autonomous cmood agent and file system watcher.",
    version="0.1.0"
)

# Mount static files for the frontend
app.mount("/static", StaticFiles(directory="public"), name="static")

# --- Startup and Shutdown Events ---
observer = None
watcher_thread = None

@app.on_event("startup")
async def startup_event():
    global observer

    # Ensure the watched directory exists
    os.makedirs(cmood_state.watched_directory, exist_ok=True)
    cmood_state.add_log(f"Ensured watched directory exists: {cmood_state.watched_directory}")

    # Initialize watchdog observer
    observer = Observer()
    event_handler = CMoodFileSystemEventHandler()
    observer.schedule(event_handler, cmood_state.watched_directory, recursive=True)

    # Start observer in a separate thread
    observer.start()
    cmood_state.add_log(f"cmood agent initialized and watching {cmood_state.watched_directory}")

    # Simulate initial agent status
    cmood_state.update_agent_status(
        ci="Working",
        cloud="Working",
        mood="Working",
        wait="Working"
    )
    cmood_state.add_log("Initial cmood agent status set to 'Working'")

    # Simulate some initial logs as seen in the image
    cmood_state.add_log("Started server process [1]")
    cmood_state.add_log("Waiting for application startup.")
    cmood_state.add_log("Application startup complete.")
    cmood_state.add_log("Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)")


@app.on_event("shutdown")
async def shutdown_event():
    if observer:
        observer.stop()
        observer.join()
        cmood_state.add_log("cmood file system watcher stopped.")

# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse, summary="Serve the cmood dashboard")
async def read_root():
    """Serves the main HTML dashboard for the cmood agent."""
    with open("public/index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/status", response_class=JSONResponse, summary="Get cmood agent and watcher status")
async def get_status():
    """Returns the current status of the cmood agent, file system watcher, and logs."""
    return {
        "cmood_agent_status": {
            "ci_clone": cmood_state.ci_clone_status,
            "cloud_clone": cmood_state.cloud_clone_status,
            "mood_agent": cmood_state.mood_agent_status,
            "wait_arguments_with_agent": cmood_state.wait_arguments_status,
        },
        "file_system_watcher": {
            "watching_directory": cmood_state.watched_directory,
            "last_event": cmood_state.last_event["type"],
            "last_event_path": cmood_state.last_event["path"],
            "timestamp": cmood_state.last_event["timestamp"],
        },
        "fastapi_endpoints": [ # Static as per image
            {"path": "/", "method": "GET"},
            {"path": "/status", "method": "GET"},
            {"path": "/collect", "method": "POST"},
            {"path": "/clone", "method": "POST"},
        ],
        "logs": cmood_state.logs,
    }

@app.post("/collect", summary="Initiate file collection")
async def collect_files(request: Request):
    """Placeholder for initiating file collection."""
    data = await request.json()
    cmood_state.add_log(f"Collection initiated with data: {data}")
    return {"message": "Collection process started", "data_received": data}

@app.post("/clone", summary="Initiate cloud cloning")
async def clone_files(request: Request):
    """Placeholder for initiating cloud cloning."""
    data = await request.json()
    cmood_state.add_log(f"Cloning initiated with data: {data}")
    return {"message": "Cloning process started", "data_received": data}

# To run the application: uvicorn cmood:app --host 0.0.0.0 --port 8000
