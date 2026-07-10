import os

class WorkerConfig:
    WORKER_ID = os.getenv("DEPLOYMENT_WORKER_ID", "worker-01")
    CENTRAL_API_URL = os.getenv("AMOSCLAUD_API_URL", "http://localhost:3000")
    WORKSPACE_DIR = os.getenv("WORKER_WORKSPACE_DIR", "./workspace")
    POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "5"))
    API_KEY = os.getenv("AMOSCLAUD_API_KEY", "cmood-super-secret-token-9988")
