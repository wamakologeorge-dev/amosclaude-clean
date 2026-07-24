import time
import logging
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from cmood.config import settings
from cmood.orchestrator import orchestrator

logger = logging.getLogger("cmood.collector")

class TrueFileCollectorHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.last_triggered: dict[str, float] = {}
        self.debounce_interval = 1.0  # seconds

    def _should_process(self, path: str) -> bool:
        # Ignore hidden files, directories, and git files
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
