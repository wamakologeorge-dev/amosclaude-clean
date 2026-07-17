"""API routes package."""

# Re-export the Doctor modules. They are mounted directly by create_app so
# FastAPI exposes concrete routes instead of nested router wrappers.
from amoscloud_ai.api.routes import admin as admin
from amoscloud_ai.api.routes import doctor_medical as doctor_medical
from amoscloud_ai.api.routes import doctor_travel as doctor_travel

# Keep one public Autonomous router while allowing its state and results API to
# live in a focused backend module. create_app already mounts agent.router at
# /api/v1, so these routes are exposed under /api/v1/agent/autonomous.
from amoscloud_ai.api.routes import agent as agent
from amoscloud_ai.api.routes import autonomous_state as autonomous_state

agent.router.include_router(autonomous_state.router)
