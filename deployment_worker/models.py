from pydantic import BaseModel
from typing import Dict, Optional, List

class DeploymentTask(BaseModel):
    deployment_id: str
    repo_url: str
    branch: str = "main"
    build_command: Optional[str] = None
    start_command: str
    env_vars: Dict[str, str] = {}
    port: int = 8000

class DeploymentStatusUpdate(BaseModel):
    worker_id: str
    deployment_id: str
    status: str  # PENDING, BUILDING, RUNNING, FAILED, SUCCESS
    logs: str
