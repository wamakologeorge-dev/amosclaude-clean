"""Amosclaud plugin and extension infrastructure."""

from .registry import (
    AmosclaudPlugin,
    PluginContext,
    PluginManifest,
    PluginRegistry,
    build_registry,
)

__all__ = [
    "AmosclaudPlugin",
    "PluginContext",
    "PluginManifest",
    "PluginRegistry",
    "build_registry",
]
