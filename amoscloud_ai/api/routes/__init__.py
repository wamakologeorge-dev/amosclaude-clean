"""API routes package."""

# Re-export the Doctor modules. They are mounted directly by create_app so
# FastAPI exposes concrete routes instead of nested router wrappers.
from amoscloud_ai.api.routes import admin as admin
from amoscloud_ai.api.routes import doctor_medical as doctor_medical
from amoscloud_ai.api.routes import doctor_travel as doctor_travel

# Extend the existing repository router without adding another application-level
# mount. This keeps all repository endpoints under /api/v1/repositories.
from amoscloud_ai.api.routes import repository_templates as repository_templates
from amoscloud_ai.api.routes import real_repositories as real_repositories

repository_templates.router.include_router(real_repositories.router)
