"""API routes package."""

# Doctor Medical is mounted under the existing administrator router so the
# self-healing APIs remain owner-only.
from amoscloud_ai.api.routes import admin as admin
from amoscloud_ai.api.routes import agent as agent
from amoscloud_ai.api.routes import doctor_medical as doctor_medical
from amoscloud_ai.api.routes import doctor_travel as doctor_travel

# Preserve the established public API identity while the user-facing console
# continues to describe the capability as an Agent Assistant. Engineering
# verification behavior remains implemented by the agent route itself.
agent.AGENT_NAME = "Amosclaud Autonomous Runtime"
agent.AGENT_ROLE = "autonomous build, deployment, and monitoring runtime"
agent.AGENT_MODE = "autonomous"

admin.router.include_router(doctor_medical.router)
admin.router.include_router(doctor_travel.router)
