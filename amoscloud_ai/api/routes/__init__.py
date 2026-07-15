"""API routes package."""

# Doctor Medical is mounted under the existing administrator router so the
# self-healing API becomes available without weakening its owner-only access.
from amoscloud_ai.api.routes import admin as admin
from amoscloud_ai.api.routes import doctor_medical as doctor_medical

admin.router.include_router(doctor_medical.router)
