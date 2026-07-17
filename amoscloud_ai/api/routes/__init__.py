"""API routes package."""

# Re-export the Doctor modules. They are mounted directly by create_app so
# FastAPI exposes concrete routes instead of nested router wrappers.
from amoscloud_ai.api.routes import admin as admin
from amoscloud_ai.api.routes import doctor_medical as doctor_medical
from amoscloud_ai.api.routes import doctor_travel as doctor_travel
