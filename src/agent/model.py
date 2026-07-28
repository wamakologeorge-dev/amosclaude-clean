"""Single cloud-model gateway used by every Amosclaud agent capability."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from amoscloud_ai import provider as native_provider

from .prompts import SYSTEM_PROMPT


@dataclass(frozen=True)
class ModelConfig:
    endpoint: str
    model: str
    api_key: str | None
    timeout_seconds: int = 90
    provider: str = "amosclaud-model"
    completions_path: str = "/v1/chat/completions"


def _first_value(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def load_model_config() -> ModelConfig:
    """Describe the native route selected by Amosclaud's shared provider policy.

    Selection itself lives in :mod:`amoscloud_ai.provider`, which tries native
    Amosclaud model routes before considering explicitly enabled adapters.
    """
    endpoint = _first_value(
        "AMOSCLAUD_MODEL_ENDPOINT",
        "AMOSCLAUD_MODEL_URL",
        "AMOSCLAUD_BOT_URL",
    ).rstrip("/")
    provider = "amosclaud-model"
    completions_path = _first_value("AMOSCLAUD_MODEL_COMPLETIONS_PATH") or "/v1/chat/completions"
    model = _first_value("AMOSCLAUD_MODEL", "AMOSCLAUD_API_MODEL") or "amosclaud-folder-v1"
    api_key = _first_value("AMOSCLAUD_MODEL_TOKEN") or None

    if endpoint == _first_value("AMOSCLAUD_BOT_URL").rstrip("/") and endpoint:
        provider = "amosclaud-bot"
        completions_path = _first_value("AMOSCLAUD_BOT_COMPLETIONS_PATH") or completions_path
        api_key = _first_value("AMOSCLAUD_BOT_TOKEN", "AMOSCLAUD_MODEL_TOKEN") or api_key
    elif not endpoint:
        api_endpoint = _first_value("AMOSCLAUD_PROVIDER_API_URL", "AMOSCLAUD_API_URL").rstrip("/")
        api_token = _first_value("AMOSCLAUD_API_KEY")
        if api_endpoint and api_token:
            endpoint = api_endpoint
            provider = "amosclaud-api"
            completions_path = (
                _first_value("AMOSCLAUD_API_COMPLETIONS_PATH")
                or "/api/v1/provider/chat/completions"
            )
            api_key = api_token

    timeout_raw = _first_value("AMOSCLAUD_MODEL_TIMEOUT") or "90"
    try:
        timeout_seconds = max(1, int(timeout_raw))
    except ValueError as exc:
        raise ValueError("AMOSCLAUD_MODEL_TIMEOUT must be an integer") from exc

    if completions_path and not completions_path.startswith("/"):
        completions_path = f"/{completions_path}"

    return ModelConfig(
        endpoint=endpoint,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        provider=provider,
        completions_path=completions_path,
    )


class AutonomousModelGateway:
    """Shared-provider gateway for planning, debugging, review, and repair prompts."""

    MAX_EVIDENCE_CHARS = 32_000
    _FILE_REQUEST = re.compile(
        r"\bcreate\s+(?:a\s+)?new\s+file\s+(?:named|called)\s+" r"[`\"']?([A-Za-z0-9_.\-/]+)",
        re.IGNORECASE,
    )

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or load_model_config()

    def available(self) -> bool:
        return native_provider.is_configured()

    def describe(self) -> dict[str, Any]:
        return {
            "mode": "remote-http-api",
            "loads_local_weights": False,
            "provider": self.config.provider,
            "model": self.config.model,
            "endpoint_configured": bool(self.config.endpoint),
            "completions_path": self.config.completions_path,
            "token_configured": bool(self.config.api_key),
            "timeout_seconds": self.config.timeout_seconds,
        }

    @classmethod
    def _bounded_evidence(cls, evidence: list[str]) -> str:
        selected: list[str] = []
        remaining = cls.MAX_EVIDENCE_CHARS
        for item in evidence:
            text = str(item).strip()
            if not text or remaining <= 0:
                continue
            fragment = text[:remaining]
            selected.append(fragment)
            remaining -= len(fragment)
        return "\n\n---\n\n".join(selected)

    @classmethod
    def _deterministic_file_creation(cls, objective: str) -> str | None:
        """Handle explicit, low-risk documentation creation without a model.

        This is intentionally narrow. It gives the GitHub bot a reliable proof of
        real write execution while preserving the model requirement for source
        code changes and ambiguous requests.
        """
        match = cls._FILE_REQUEST.search(objective or "")
        if not match:
            return None

        path = match.group(1).strip().replace("\\", "/").rstrip(".,;:")
        pure = PurePosixPath(path)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or not path.startswith("docs/")
            or pure.suffix.lower() != ".md"
        ):
            return None

        lowered = " ".join((objective or "").lower().split())
        repository = os.getenv("GITHUB_REPOSITORY", "unknown/repository").strip()
        executed = datetime.now(timezone.utc).date().isoformat()
        title = pure.stem.replace("_", " ").replace("-", " ").title()
        details: list[str] = []

        if "current repository name" in lowered:
            details.append(f"- **Repository:** `{repository}`")
        if "purpose of this test" in lowered:
            details.append(
                "- **Purpose:** Verify that Amosclaud can complete a guarded, real repository write."
            )
        if "date the task was executed" in lowered:
            details.append(f"- **Executed:** `{executed}`")
        if "amosclaud created a real repository change" in lowered:
            details.append("- **Result:** Amosclaud created a real repository change.")

        if not details:
            return None

        content = f"# {title}\n\n" + "\n".join(details) + "\n"
        return json.dumps(
            {
                "diagnosis": (
                    "The request is an explicit low-risk Markdown creation task "
                    "and can be completed deterministically without external inference."
                ),
                "changes": [
                    {
                        "path": path,
                        "content": content,
                        "reason": "Create the exact requested repository action-test document.",
                    }
                ],
                "verification": [
                    f"Confirm {path} exists and contains the requested repository, purpose, date, and result fields."
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def complete(self, objective: str, evidence: list[str]) -> str:
        """Generate one bounded, machine-readable repair proposal."""
        deterministic = self._deterministic_file_creation(objective)
        if deterministic is not None:
            return deterministic

        user_content = (
            "Create the smallest safe repository repair for the verified "
            "objective below.\n\n"
            f"OBJECTIVE\n{objective}\n\n"
            "VERIFIED REPOSITORY EVIDENCE\n"
            f"{self._bounded_evidence(evidence)}\n\n"
            "Return ONLY one JSON object with this exact shape:\n"
            '{"diagnosis":"verified root cause or remaining uncertainty",'
            '"changes":[{"path":"relative/path",'
            '"content":"complete replacement UTF-8 file content",'
            '"reason":"why this file is required"}],'
            '"verification":["focused command or check"]}\n\n'
            "Rules:\n"
            "- Propose at most 8 files and prefer fewer.\n"
            "- Every content value must contain the COMPLETE final file, "
            "never a diff or ellipsis.\n"
            "- Do not modify secrets, credentials, generated data, .git, "
            "deployment control files, GitHub workflow files, CODEOWNERS, "
            "or security policy files.\n"
            "- Preserve existing public behavior except for the requested repair.\n"
            "- Add or update a focused regression test when practical.\n"
            "- When evidence is insufficient, return an empty changes list "
            "and explain what is missing.\n"
            "- Do not wrap the JSON in Markdown."
        )
        result = native_provider.reply(
            [{"role": "user", "content": user_content}],
            SYSTEM_PROMPT,
        )
        if not result.ok:
            raise RuntimeError(result.error or "Amosclaud execution model is not configured")
        return result.reply

    def plan(self, objective: str, evidence: list[str]) -> list[str]:
        """Return a stable plan without claiming that model execution occurred."""
        plan = [
            "Define the exact failure and observable success criteria",
            "Inspect bounded repository files relevant to the objective",
        ]
        if evidence:
            plan.append(f"Prioritize the first verified blocker: {evidence[0][:160]}")
        plan.extend(
            [
                "Ask the connected Ollama route for a structured minimal " "change proposal",
                "Apply only authorized files inside the designated workspace",
                "Run focused verification for the changed files before publishing",
                "Create a branch and pull request only after verification passes",
            ]
        )
        return plan
