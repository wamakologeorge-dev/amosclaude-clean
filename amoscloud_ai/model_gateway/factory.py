"""Environment-backed gateway construction with first-party preference."""

from __future__ import annotations

import os

from .providers import (
    AnthropicProvider,
    GeminiProvider,
    LegacyAmosclaudProvider,
    OpenAICompatibleProvider,
)
from .registry import ProviderRegistry
from .router import UniversalModelGateway

_TRUE_VALUES = {"1", "true", "yes", "on"}
_PRIVACY_VALUES = {"local", "first_party", "external"}


def _enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE_VALUES


def _privacy(name: str, default: str) -> str:
    value = os.getenv(name, default).strip() or default
    return value if value in _PRIVACY_VALUES else default


def build_default_gateway() -> UniversalModelGateway:
    """Build the default registry without changing the legacy runtime path."""

    registry = ProviderRegistry()
    registry.register(LegacyAmosclaudProvider())

    compatible_url = os.getenv("AMOSCLAUD_OPENAI_COMPAT_URL", "").strip()
    compatible_model = os.getenv("AMOSCLAUD_OPENAI_COMPAT_MODEL", "").strip()
    if compatible_url and compatible_model:
        registry.register(
            OpenAICompatibleProvider(
                key="openai-compatible",
                base_url=compatible_url,
                model=compatible_model,
                api_key=os.getenv("AMOSCLAUD_OPENAI_COMPAT_TOKEN", ""),
                priority=80,
                privacy=_privacy(
                    "AMOSCLAUD_OPENAI_COMPAT_PRIVACY", "first_party"
                ),
            )
        )

    if not _enabled("AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS"):
        return UniversalModelGateway(registry=registry)

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        registry.register(
            OpenAICompatibleProvider(
                key="openai",
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com").strip(),
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
                api_key=openai_key,
                priority=30,
                privacy="external",
            )
        )

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if anthropic_key:
        registry.register(
            AnthropicProvider(
                api_key=anthropic_key,
                model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest").strip(),
                priority=25,
            )
        )

    gemini_key = (
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )
    if gemini_key:
        registry.register(
            GeminiProvider(
                api_key=gemini_key,
                model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip(),
                priority=20,
            )
        )

    return UniversalModelGateway(registry=registry)
