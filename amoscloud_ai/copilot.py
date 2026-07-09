"""Amosclaud Copilot identity and replies."""

from __future__ import annotations

from amoscloud_ai.models import DeploymentStatus, PipelineStatus


COPILOT_NAME = "Amosclaud Copilot"
COPILOT_OWNER = "Amosclaud"
COPILOT_ROLE = "higher-level delegation agent"
COPILOT_HOME = "amosclaud.com"
COPILOT_PIPELINE = "Amosclaud pipeline"
COPILOT_MISSION = (
    f"{COPILOT_NAME} delegates, builds, monitors, and reports only for "
    f"{COPILOT_HOME} and the {COPILOT_PIPELINE}."
)
COPILOT_SCOPE = [
    COPILOT_HOME,
    COPILOT_PIPELINE,
]
COPILOT_DIRECTIVES = [
    "Delegate Amosclaud.com work to the pipeline.",
    "Build and monitor the Amosclaud pipeline.",
    "Reply back with pipeline state changes.",
    "Stay inside Amosclaud-owned application work.",
]


PIPELINE_REPLIES = {
    PipelineStatus.PENDING: (
        f"{COPILOT_NAME}: I accepted this as {COPILOT_ROLE} for {COPILOT_HOME}. "
        f"I am delegating it into the {COPILOT_PIPELINE} and preparing the build."
    ),
    PipelineStatus.RUNNING: (
        f"{COPILOT_NAME}: I am building through the {COPILOT_PIPELINE} now. "
        "I will reply back when the pipeline finishes."
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
        f"{COPILOT_NAME}: I queued the {COPILOT_HOME} deployment for the {COPILOT_PIPELINE}."
    ),
    DeploymentStatus.IN_PROGRESS: (
        f"{COPILOT_NAME}: I am delegating, building, and deploying through the "
        f"{COPILOT_PIPELINE}. I will reply back when it finishes."
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
