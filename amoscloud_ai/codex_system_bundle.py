"""Build the canonical Amosclaud Codex system bundle."""
from __future__ import annotations

import os
from typing import Any

from amoscloud_ai.mapping_bundles import BundleRecord, MappingBundleStore

BUNDLE_NAME = "amosclaud-codex-system"
BUNDLE_VERSION = "1.0.0"


def codex_system_manifest() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return Codex runtime mappings and safe metadata."""
    mappings: dict[str, Any] = {
        "runtime": {
            "engine": "codex-compatible",
            "provider": "openai",
            "api": "responses",
            "model_env": "AMOSCLAUD_CODEX_MODEL",
            "credential_env": "OPENAI_API_KEY",
            "store_responses": False,
        },
        "agent_loop": {
            "stages": ["observe", "plan", "act", "verify", "remember"],
            "planning_required": True,
            "verification_required": True,
            "evidence_required": True,
        },
        "tools": {
            "read": ["repository.read", "file.read", "search", "tests.read", "ci.read"],
            "write": ["file.write", "repository.patch", "tests.run"],
            "approval_required": ["shell.exec", "git.push", "deploy", "secret.write", "delete"],
        },
        "workspace": {
            "root_env": "AMOSCLAUD_WORKSPACE",
            "confined": True,
            "allow_parent_traversal": False,
            "allow_secret_files": False,
        },
        "limits": {
            "max_iterations": int(os.getenv("AMOSCLAUD_AGENT_MAX_ITERATIONS", "8")),
            "max_tool_calls": int(os.getenv("AMOSCLAUD_AGENT_MAX_TOOL_CALLS", "40")),
            "max_changed_files": int(os.getenv("AMOSCLAUD_AGENT_MAX_CHANGED_FILES", "12")),
            "max_retries": 2,
        },
        "verification": {
            "required_checks": ["syntax", "targeted-tests", "diff-review"],
            "completion_requires_pass": True,
            "rollback_on_failure": True,
        },
        "authentication": {
            "client_key_type": "amosclaud-autonomous-key",
            "upstream_key_type": "server-side-openai-key",
            "expose_upstream_key": False,
        },
        "openai_compatibility": {
            "base_url": "/v1",
            "models_route": "/v1/models",
            "chat_route": "/v1/chat/completions",
        },
    }
    metadata = {
        "kind": "codex-system-bundle",
        "schema": "amosclaud.codex-system/v1",
        "owner": "Amosclaud",
        "purpose": "autonomous software engineering runtime configuration",
        "contains_secrets": False,
        "media_type": "application/vnd.amosclaud.bytes",
    }
    return mappings, metadata


def create_codex_system_bundle(
    store: MappingBundleStore | None = None,
    *,
    version: str = BUNDLE_VERSION,
) -> BundleRecord:
    """Create or replace the canonical Codex system bundle."""
    target = store or MappingBundleStore()
    mappings, metadata = codex_system_manifest()
    return target.create(
        name=BUNDLE_NAME,
        version=version,
        mappings=mappings,
        metadata=metadata,
    )
