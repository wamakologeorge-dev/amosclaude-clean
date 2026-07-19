"""API routes package and FastAPI router compatibility helpers.

Some FastAPI/Starlette combinations preserve an included ``APIRouter`` as a
nested wrapper.  Amosclaud's route contracts intentionally inspect the
application's top-level route table, so wrappers with ``path == ''`` made real
endpoints appear unregistered.  Install a small compatibility implementation
before importing route modules so nested service routers are copied as concrete
``APIRoute`` and websocket entries.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute, APIWebSocketRoute


def _join_prefix(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path or path == "/":
        return prefix or "/"
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _flat_include_router(
    self: APIRouter | FastAPI,
    router: APIRouter,
    *,
    prefix: str = "",
    tags: list[str] | None = None,
    dependencies: list[Any] | None = None,
    default_response_class: Any = None,
    responses: dict[int | str, dict[str, Any]] | None = None,
    callbacks: list[Any] | None = None,
    deprecated: bool | None = None,
    include_in_schema: bool = True,
    generate_unique_id_function: Any = None,
    **_: Any,
) -> None:
    """Include every child route directly instead of retaining router wrappers."""

    target = self.router if isinstance(self, FastAPI) else self
    inherited_tags = list(tags or [])
    inherited_dependencies = list(dependencies or [])
    inherited_responses = dict(responses or {})
    inherited_callbacks = list(callbacks or [])

    for route in list(router.routes):
        if isinstance(route, APIRouter):
            _flat_include_router(
                self,
                route,
                prefix=_join_prefix(prefix, getattr(route, "prefix", "")),
                tags=inherited_tags,
                dependencies=inherited_dependencies,
                responses=inherited_responses,
                callbacks=inherited_callbacks,
                deprecated=deprecated,
                include_in_schema=include_in_schema,
                generate_unique_id_function=generate_unique_id_function,
            )
            continue

        if isinstance(route, APIRoute):
            combined_responses = {**inherited_responses, **(route.responses or {})}
            target.add_api_route(
                _join_prefix(prefix, route.path),
                route.endpoint,
                response_model=route.response_model,
                status_code=route.status_code,
                tags=[*inherited_tags, *(route.tags or [])],
                dependencies=[*inherited_dependencies, *(route.dependencies or [])],
                summary=route.summary,
                description=route.description,
                response_description=route.response_description,
                responses=combined_responses,
                deprecated=deprecated if deprecated is not None else route.deprecated,
                methods=route.methods,
                operation_id=route.operation_id,
                response_model_include=route.response_model_include,
                response_model_exclude=route.response_model_exclude,
                response_model_by_alias=route.response_model_by_alias,
                response_model_exclude_unset=route.response_model_exclude_unset,
                response_model_exclude_defaults=route.response_model_exclude_defaults,
                response_model_exclude_none=route.response_model_exclude_none,
                include_in_schema=include_in_schema and route.include_in_schema,
                response_class=(
                    route.response_class
                    if default_response_class is None
                    else default_response_class
                ),
                name=route.name,
                callbacks=[*inherited_callbacks, *(route.callbacks or [])],
                openapi_extra=route.openapi_extra,
                generate_unique_id_function=(
                    generate_unique_id_function
                    or route.generate_unique_id_function
                ),
            )
            continue

        if isinstance(route, APIWebSocketRoute):
            target.add_api_websocket_route(
                _join_prefix(prefix, route.path),
                route.endpoint,
                name=route.name,
                dependencies=[*inherited_dependencies, *(route.dependencies or [])],
            )
            continue

        # Preserve Starlette mounts and ordinary routes. They do not create the
        # empty APIRouter wrappers that caused this failure.
        target.routes.append(route)


# Install before importing route modules; those modules compose several routers
# during import. The marker prevents duplicate patching in reload/test sessions.
if not getattr(APIRouter.include_router, "_amosclaud_flattened", False):
    _flat_include_router._amosclaud_flattened = True  # type: ignore[attr-defined]
    APIRouter.include_router = _flat_include_router  # type: ignore[assignment]
    FastAPI.include_router = _flat_include_router  # type: ignore[assignment]


# Re-export the Doctor modules. They are mounted directly by create_app.
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

# Amosclaud is the source-control and project-management authority. Attach these
# routes to the native repository router so create_app mounts one service surface.
from amoscloud_ai.api.routes import profile as profile
from amoscloud_ai.api.routes import repositories as repositories
from amoscloud_ai.api.routes import solo_development as solo_development
from repository import git_server as native_git

_native_paths = {getattr(route, "path", None) for route in repositories.router.routes}
for _module in (solo_development, profile, native_git):
    for _route in _module.router.routes:
        if getattr(_route, "path", None) not in _native_paths:
            repositories.router.routes.append(_route)
            _native_paths.add(getattr(_route, "path", None))
