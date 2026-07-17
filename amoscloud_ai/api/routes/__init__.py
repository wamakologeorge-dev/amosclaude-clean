"""API routes package."""

# Doctor Medical is mounted under the existing administrator router so the
# self-healing APIs remain owner-only.
from amoscloud_ai.api.routes import admin as admin
from amoscloud_ai.api.routes import doctor_medical as doctor_medical
from amoscloud_ai.api.routes import doctor_travel as doctor_travel

admin.router.include_router(doctor_medical.router)
admin.router.include_router(doctor_travel.router)
