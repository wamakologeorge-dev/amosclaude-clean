"""
Amosclaud Platform — Software creation, developer tools, and AI-powered building.

This package exposes the core platform components:
  - SoftwareCreator : project scaffolding and template generation
  - DeveloperTools  : linting, formatting, testing, and debugging helpers
  - BuildEngine     : multi-language build automation and artifact management
  - AIAssistant     : Amosclaud-AI powered code generation and review
  - PlatformAPI     : FastAPI REST interface
  - PlatformCLI     : command-line interface
"""

from src.platform.software_creator import SoftwareCreator
from src.platform.developer_tools import DeveloperTools
from src.platform.build_engine import BuildEngine
from src.platform.ai_assistant import AIAssistant

__version__ = "1.0.0"
__all__ = [
    "SoftwareCreator",
    "DeveloperTools",
    "BuildEngine",
    "AIAssistant",
]
