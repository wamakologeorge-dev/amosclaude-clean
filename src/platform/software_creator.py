"""
SoftwareCreator — Project scaffolding and template-based software creation.

Supports multiple project types (web API, CLI tool, library, microservice) and
generates the full directory skeleton with starter files so developers can go
from zero to a working project in seconds using Amosclaud-AI.
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ProjectType(Enum):
    """Supported project archetypes."""
    WEB_API = "web_api"
    CLI_TOOL = "cli_tool"
    LIBRARY = "library"
    MICROSERVICE = "microservice"
    FULL_STACK = "full_stack"
    DATA_PIPELINE = "data_pipeline"


@dataclass
class ProjectConfig:
    """Configuration for a new software project."""
    name: str
    project_type: ProjectType
    language: str = "python"
    description: str = ""
    author: str = ""
    version: str = "0.1.0"
    output_dir: str = "."
    features: List[str] = field(default_factory=list)
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class CreationResult:
    """Result of a project creation operation."""
    success: bool
    project_path: str
    files_created: List[str]
    message: str
    created_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Built-in project templates
# ---------------------------------------------------------------------------

_TEMPLATES: Dict[ProjectType, Dict[str, str]] = {
    ProjectType.WEB_API: {
        "main.py": '''\
"""Entry point for {name} web API."""

from fastapi import FastAPI

app = FastAPI(title="{name}", version="{version}", description="{description}")


@app.get("/health")
def health() -> dict:
    return {{"status": "ok", "service": "{name}"}}


@app.get("/")
def root() -> dict:
    return {{"message": "Welcome to {name}"}}
''',
        "requirements.txt": "fastapi>=0.100.0\nuvicorn[standard]>=0.23.0\n",
        "README.md": "# {name}\n\n{description}\n\n## Run\n\n```bash\nuvicorn main:app --reload\n```\n",
        "Dockerfile": '''\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
''',
    },
    ProjectType.CLI_TOOL: {
        "{name}/cli.py": '''\
"""CLI entry point for {name}."""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="{description}")
    parser.add_argument("--version", action="version", version="{version}")
    args = parser.parse_args()
    print("Welcome to {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
        "setup.py": '''\
from setuptools import setup, find_packages

setup(
    name="{name}",
    version="{version}",
    author="{author}",
    description="{description}",
    packages=find_packages(),
    entry_points={{"console_scripts": ["{name}={name}.cli:main"]}},
    python_requires=">=3.9",
)
''',
        "README.md": "# {name}\n\n{description}\n\n## Install\n\n```bash\npip install -e .\n```\n",
    },
    ProjectType.LIBRARY: {
        "{name}/__init__.py": '''\
"""{name} — {description}"""

__version__ = "{version}"
__author__ = "{author}"
''',
        "{name}/core.py": '''\
"""Core functionality for {name}."""

import logging

logger = logging.getLogger(__name__)


class {class_name}:
    """Main class for {name}."""

    def __init__(self) -> None:
        logger.info("{name} initialised")
''',
        "tests/__init__.py": "",
        "tests/test_core.py": '''\
"""Tests for {name}.core."""

from {name}.core import {class_name}


def test_instantiation() -> None:
    obj = {class_name}()
    assert obj is not None
''',
        "README.md": "# {name}\n\n{description}\n",
        "setup.py": '''\
from setuptools import setup, find_packages

setup(
    name="{name}",
    version="{version}",
    author="{author}",
    description="{description}",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.9",
)
''',
    },
    ProjectType.MICROSERVICE: {
        "app/__init__.py": "",
        "app/main.py": '''\
"""Microservice: {name}"""

from fastapi import FastAPI
from app.routes import router

app = FastAPI(title="{name}", version="{version}")
app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    return {{"status": "healthy", "service": "{name}"}}
''',
        "app/routes.py": '''\
"""API routes for {name}."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def index() -> dict:
    return {{"service": "{name}", "version": "{version}"}}
''',
        "requirements.txt": "fastapi>=0.100.0\nuvicorn[standard]>=0.23.0\nhttpx>=0.24.0\n",
        "Dockerfile": '''\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
''',
        "README.md": "# {name}\n\n{description}\n",
    },
    ProjectType.DATA_PIPELINE: {
        "pipeline/__init__.py": "",
        "pipeline/runner.py": '''\
"""Data pipeline runner for {name}."""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Orchestrate data pipeline stages."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.stages: List[str] = []

    def add_stage(self, stage_name: str) -> None:
        self.stages.append(stage_name)
        logger.info("Stage added: %s", stage_name)

    def run(self) -> bool:
        logger.info("Running pipeline: {name}")
        for stage in self.stages:
            logger.info("Executing stage: %s", stage)
        logger.info("Pipeline complete")
        return True
''',
        "requirements.txt": "pandas>=2.0.0\npyarrow>=12.0.0\n",
        "README.md": "# {name}\n\n{description}\n",
    },
    ProjectType.FULL_STACK: {
        "backend/main.py": '''\
"""Backend API for {name}."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="{name} API", version="{version}")


@app.get("/api/health")
def health() -> dict:
    return {{"status": "ok"}}
''',
        "backend/requirements.txt": "fastapi>=0.100.0\nuvicorn[standard]>=0.23.0\n",
        "frontend/index.html": '''\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
</head>
<body>
  <h1>Welcome to {name}</h1>
  <p>{description}</p>
  <script>
    fetch("/api/health").then(r => r.json()).then(d => console.log(d));
  </script>
</body>
</html>
''',
        "README.md": "# {name}\n\n{description}\n\n## Start backend\n\n```bash\ncd backend && uvicorn main:app --reload\n```\n",
    },
}


class SoftwareCreator:
    """
    Create new software projects from templates powered by Amosclaud-AI.

    Usage::

        creator = SoftwareCreator()
        result = creator.create_project(ProjectConfig(
            name="my-api",
            project_type=ProjectType.WEB_API,
            description="My awesome API",
        ))
        print(result.project_path)
    """

    def __init__(self, templates_dir: Optional[str] = None) -> None:
        self._templates_dir = Path(templates_dir) if templates_dir else None
        self._history: List[CreationResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_project(self, config: ProjectConfig) -> CreationResult:
        """Scaffold a new project from the given configuration."""
        project_path = Path(config.output_dir) / config.name
        try:
            logger.info("Creating project '%s' (%s)", config.name, config.project_type.value)

            if project_path.exists():
                return CreationResult(
                    success=False,
                    project_path=str(project_path),
                    files_created=[],
                    message=f"Directory '{project_path}' already exists.",
                )

            project_path.mkdir(parents=True)
            files_created = self._render_template(config, project_path)

            result = CreationResult(
                success=True,
                project_path=str(project_path),
                files_created=files_created,
                message=f"Project '{config.name}' created successfully.",
            )
            self._history.append(result)
            logger.info("Project created at %s (%d files)", project_path, len(files_created))
            return result

        except Exception as exc:
            logger.error("Project creation failed: %s", exc)
            if project_path.exists():
                shutil.rmtree(project_path, ignore_errors=True)
            return CreationResult(
                success=False,
                project_path=str(project_path),
                files_created=[],
                message=str(exc),
            )

    def list_templates(self) -> List[str]:
        """Return the names of all built-in project types."""
        return [pt.value for pt in ProjectType]

    def get_creation_history(self) -> List[CreationResult]:
        """Return all previously created projects in this session."""
        return list(self._history)

    def add_custom_template(
        self, project_type_name: str, files: Dict[str, str]
    ) -> None:
        """
        Register a custom template under a new project type name.

        *project_type_name* must not conflict with existing ProjectType values.
        """
        if any(pt.value == project_type_name for pt in ProjectType):
            raise ValueError(
                f"'{project_type_name}' conflicts with a built-in project type."
            )
        # Extend the runtime template map with a sentinel key string.
        _TEMPLATES[project_type_name] = files  # type: ignore[index]
        logger.info("Custom template registered: %s", project_type_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_template(
        self, config: ProjectConfig, project_path: Path
    ) -> List[str]:
        """Write all template files for *config* into *project_path*."""
        template_files = _TEMPLATES.get(config.project_type, {})
        class_name = "".join(word.capitalize() for word in config.name.replace("-", "_").split("_"))
        fmt_vars = {
            "name": config.name,
            "description": config.description,
            "author": config.author,
            "version": config.version,
            "class_name": class_name,
        }

        files_created: List[str] = []
        for rel_path, content_template in template_files.items():
            rel_path_rendered = rel_path.format(**fmt_vars)
            file_path = project_path / rel_path_rendered
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content_template.format(**fmt_vars), encoding="utf-8")
            files_created.append(rel_path_rendered)

        # Always create a .gitignore
        gitignore = project_path / ".gitignore"
        gitignore.write_text(
            "__pycache__/\n*.pyc\n*.pyo\n.env\n.venv\ndist/\nbuild/\n*.egg-info/\n",
            encoding="utf-8",
        )
        files_created.append(".gitignore")

        return files_created
