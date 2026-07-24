"""Amosclaud autonomous server identity and replies."""

from __future__ import annotations

from amoscloud_ai.models import DeploymentStatus, PipelineStatus


COPILOT_NAME = "Amosclaud Autonomous Server"
COPILOT_OWNER = "Amosclaud"
COPILOT_ROLE = "autonomous build, deployment, and monitoring server"
COPILOT_HOME = "amosclaud.com"
COPILOT_PIPELINE = "Amosclaud autonomous pipeline"
COPILOT_MISSION = (
    f"{COPILOT_NAME} checks, builds, deploys, monitors, and reports for "
    f"{COPILOT_HOME} and the {COPILOT_PIPELINE}."
)
COPILOT_SCOPE = [
    COPILOT_HOME,
    COPILOT_PIPELINE,
]
COPILOT_DIRECTIVES = [
    "Inspect Amosclaud.com repository state.",
    "Build and monitor the Amosclaud autonomous pipeline.",
    "Report pipeline state changes.",
    "Stay inside Amosclaud-owned application work.",
]


PIPELINE_REPLIES = {
    PipelineStatus.PENDING: (
        f"{COPILOT_NAME}: autonomous pipeline run queued for {COPILOT_HOME}."
    ),
    PipelineStatus.RUNNING: (
        f"{COPILOT_NAME}: autonomous pipeline run is active in the {COPILOT_PIPELINE}."
    ),
    PipelineStatus.SUCCESS: (
        f"{COPILOT_NAME}: The {COPILOT_PIPELINE} finished successfully for {COPILOT_HOME}."
    ),
    PipelineStatus.FAILED: (
        f"{COPILOT_NAME}: The {COPILOT_PIPELINE} failed. "
        "Check the pipeline logs for the failing step."
    ),
    PipelineStatus.CANCELLED: f"{COPILOT_NAME}: The {COPILOT_PIPELINE} build was cancelled.",
}


DEPLOYMENT_REPLIES = {
    DeploymentStatus.PENDING: (
        f"{COPILOT_NAME}: deployment queued for {COPILOT_HOME} in the {COPILOT_PIPELINE}."
    ),
    DeploymentStatus.IN_PROGRESS: (
        f"{COPILOT_NAME}: autonomous deployment is active through the {COPILOT_PIPELINE}."
    ),
    DeploymentStatus.COMPLETED: f"{COPILOT_NAME}: Deployment completed successfully for {COPILOT_HOME}.",
    DeploymentStatus.FAILED: (
        f"{COPILOT_NAME}: Deployment failed in the {COPILOT_PIPELINE}. "
        "Check the deployment logs for details."
    ),
    DeploymentStatus.ROLLED_BACK: f"{COPILOT_NAME}: Deployment was rolled back successfully.",
}


def pipeline_reply(status: PipelineStatus) -> str:
    return PIPELINE_REPLIES[status]


def deployment_reply(status: DeploymentStatus) -> str:
    return DEPLOYMENT_REPLIES[status]


def copilot_profile() -> dict[str, object]:
    return {
        "name": COPILOT_NAME,
        "owner": COPILOT_OWNER,
        "role": COPILOT_ROLE,
        "mission": COPILOT_MISSION,
        "home": COPILOT_HOME,
        "pipeline": COPILOT_PIPELINE,
        "scope": COPILOT_SCOPE,
        "directives": COPILOT_DIRECTIVES,
    }
