"""Frontend-facing status for the Amosclaud Autonomous backend stack."""
from fastapi import APIRouter, HTTPException, Request

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.model_services import readiness

router = APIRouter(prefix="/autonomous/model-services", tags=["autonomous-model-services"])


@router.get("")
def get_model_services(request: Request) -> dict:
    if not get_user_from_session(request.cookies.get("amos_session")):
        raise HTTPException(status_code=401, detail="Sign in to inspect Autonomous model services")
    return readiness()
