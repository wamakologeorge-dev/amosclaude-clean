import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, Optional

from deployment_worker.config import WorkerConfig
from deployment_worker.executor import DeploymentExecutor
from deployment_worker.models import DeploymentTask

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("deployment-worker")

active_deployments: Dict[str, DeploymentExecutor] = {}


def send_status_update(deployment_id: str, status: str, logs: str):
    url = f"{WorkerConfig.CENTRAL_API_URL}/api/v1/deployments/status"
    payload = {
        "worker_id": WorkerConfig.WORKER_ID,
        "deployment_id": deployment_id,
        "status": status,
        "logs": logs,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": WorkerConfig.API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except Exception as error:
        logger.error("Failed to send status update to central API: %s", error)
        return None


def fetch_next_task() -> Optional[DeploymentTask]:
    url = f"{WorkerConfig.CENTRAL_API_URL}/api/v1/deployments/pending?worker_id={WorkerConfig.WORKER_ID}"
    request = urllib.request.Request(
        url,
        headers={"X-API-Key": WorkerConfig.API_KEY},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            if data and "deployment_id" in data:
                return DeploymentTask(**data)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            body = error.read().decode("utf-8", errors="replace")
            logger.error("HTTP error fetching tasks: %s %s", error.code, body[:300])
    except Exception as error:
        logger.error("Connection error polling central API: %s", error)
    return None


def process_task(task: DeploymentTask):
    logger.info("Processing deployment task: %s", task.deployment_id)
    executor = DeploymentExecutor(
        task_id=task.deployment_id,
        repo_url=task.repo_url,
        branch=task.branch,
        env_vars=task.env_vars,
    )

    if task.deployment_id in active_deployments:
        logger.info("Stopping existing deployment for ID: %s", task.deployment_id)
        active_deployments[task.deployment_id].stop_app()

    active_deployments[task.deployment_id] = executor
    send_status_update(task.deployment_id, "BUILDING", executor.get_logs())

    if not executor.clone_repo():
        send_status_update(task.deployment_id, "FAILED", executor.get_logs())
        return
    if not executor.run_build(task.build_command):
        send_status_update(task.deployment_id, "FAILED", executor.get_logs())
        return
    if not executor.start_app(task.start_command):
        send_status_update(task.deployment_id, "FAILED", executor.get_logs())
        return

    send_status_update(task.deployment_id, "RUNNING", executor.get_logs())


def main():
    WorkerConfig.validate()
    logger.info("Starting Amosclaud Autonomous Deployment Worker: %s", WorkerConfig.WORKER_ID)
    os.makedirs(WorkerConfig.WORKSPACE_DIR, exist_ok=True)

    while True:
        try:
            task = fetch_next_task()
            if task:
                process_task(task)
            else:
                for deployment_id, executor in list(active_deployments.items()):
                    if executor.process and executor.process.poll() is not None:
                        executor.log("Application process died unexpectedly.")
                        send_status_update(deployment_id, "FAILED", executor.get_logs())
                        del active_deployments[deployment_id]
        except Exception as error:
            logger.exception("Error in deployment worker loop: %s", error)
        time.sleep(WorkerConfig.POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Worker shutting down.")
        for executor in active_deployments.values():
            executor.stop_app()
        sys.exit(0)
