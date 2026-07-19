"""API routes package."""

# Re-export the Doctor modules. They are mounted directly by create_app so
# FastAPI exposes concrete routes instead of nested router wrappers.
from amoscloud_ai.api.routes import admin as admin
from amoscloud_ai.api.routes import doctor_medical as doctor_medical
from amoscloud_ai.api.routes import doctor_travel as doctor_travel

# Extend the existing repository-template router with concrete repository routes.
from amoscloud_ai.api.routes import repository_templates as repository_templates
from amoscloud_ai.api.routes import real_repositories as real_repositories

_existing_paths = {getattr(route, "path", None) for route in repository_templates.router.routes}
for _route in real_repositories.router.routes:
    if getattr(_route, "path", None) not in _existing_paths:
        repository_templates.router.routes.append(_route)

# Amosclaud is the source-control and project-management authority. These routes
# are attached to the native repository router so create_app mounts them under
# /api/v1 without any GitHub dependency.
from amoscloud_ai.api.routes import repositories as repositories
from amoscloud_ai.api.routes import solo_development as solo_development

_native_paths = {getattr(route, "path", None) for route in repositories.router.routes}
for _route in solo_development.router.routes:
    if getattr(_route, "path", None) not in _native_paths:
        repositories.router.routes.append(_route)
