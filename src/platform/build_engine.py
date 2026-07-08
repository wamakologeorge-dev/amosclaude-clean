"""
BuildEngine — Multi-language build automation and artifact management.

Provides a pluggable build system that Amosclaud-AI can use to compile,
bundle, and package software across common language ecosystems (Python,
Node.js, Go, Java / Maven, Docker).
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BuildStatus(Enum):
    """Status of a build operation."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Language(Enum):
    """Supported build ecosystems."""
    PYTHON = "python"
    NODEJS = "nodejs"
    GO = "go"
    JAVA = "java"
    DOCKER = "docker"
    GENERIC = "generic"


@dataclass
class BuildConfig:
    """Configuration for a build job."""
    project_path: str
    language: Language = Language.PYTHON
    version: str = "latest"
    output_dir: str = "dist"
    environment: str = "production"
    extra_args: Dict[str, Any] = field(default_factory=dict)
    docker_tag: Optional[str] = None
    pre_build_commands: List[str] = field(default_factory=list)
    post_build_commands: List[str] = field(default_factory=list)


@dataclass
class BuildArtifact:
    """A file or directory produced by a build."""
    name: str
    path: str
    size_bytes: int
    artifact_type: str
    created_at: datetime = field(default_factory=datetime.now)

    def exists(self) -> bool:
        return Path(self.path).exists()


@dataclass
class BuildResult:
    """Outcome of a single build job."""
    success: bool
    language: Language
    duration_seconds: float
    log: str
    artifacts: List[BuildArtifact] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None

    def summary(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "language": self.language.value,
            "duration_seconds": round(self.duration_seconds, 2),
            "artifacts": [a.name for a in self.artifacts],
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Language-specific build strategies
# ---------------------------------------------------------------------------

class _BuildStrategy:
    """Base class for per-language build strategies."""

    def build(self, config: BuildConfig, timeout: int) -> BuildResult:
        raise NotImplementedError

    def _run(
        self,
        cmd: str,
        cwd: str,
        timeout: int,
        language: Language,
    ) -> BuildResult:
        start = datetime.now()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            duration = (datetime.now() - start).total_seconds()
            success = proc.returncode == 0
            log = (proc.stdout + proc.stderr).strip()
            return BuildResult(
                success=success,
                language=language,
                duration_seconds=duration,
                log=log,
                error=None if success else log,
            )
        except subprocess.TimeoutExpired:
            duration = (datetime.now() - start).total_seconds()
            msg = f"Build timed out after {timeout}s"
            return BuildResult(
                success=False,
                language=language,
                duration_seconds=duration,
                log=msg,
                error=msg,
            )
        except Exception as exc:
            duration = (datetime.now() - start).total_seconds()
            return BuildResult(
                success=False,
                language=language,
                duration_seconds=duration,
                log=str(exc),
                error=str(exc),
            )


class _PythonBuild(_BuildStrategy):
    def build(self, config: BuildConfig, timeout: int) -> BuildResult:
        cmd = "python -m build --wheel --outdir {out}".format(
            out=config.output_dir
        )
        return self._run(cmd, config.project_path, timeout, Language.PYTHON)


class _NodeBuild(_BuildStrategy):
    def build(self, config: BuildConfig, timeout: int) -> BuildResult:
        install = subprocess.run(
            "npm install",
            shell=True,
            capture_output=True,
            text=True,
            cwd=config.project_path,
        )
        if install.returncode != 0:
            return BuildResult(
                success=False,
                language=Language.NODEJS,
                duration_seconds=0.0,
                log=install.stderr,
                error="npm install failed",
            )
        return self._run("npm run build", config.project_path, timeout, Language.NODEJS)


class _GoBuild(_BuildStrategy):
    def build(self, config: BuildConfig, timeout: int) -> BuildResult:
        out_path = Path(config.project_path) / config.output_dir / "app"
        cmd = f"go build -o {out_path} ./..."
        return self._run(cmd, config.project_path, timeout, Language.GO)


class _JavaBuild(_BuildStrategy):
    def build(self, config: BuildConfig, timeout: int) -> BuildResult:
        mvn = shutil.which("mvn")
        if not mvn:
            return BuildResult(
                success=False,
                language=Language.JAVA,
                duration_seconds=0.0,
                log="Maven not found",
                error="Maven not found on PATH",
            )
        return self._run("mvn package -DskipTests", config.project_path, timeout, Language.JAVA)


class _DockerBuild(_BuildStrategy):
    def build(self, config: BuildConfig, timeout: int) -> BuildResult:
        tag = config.docker_tag or config.extra_args.get("tag", "app:latest")
        cmd = f"docker build -t {tag} ."
        return self._run(cmd, config.project_path, timeout, Language.DOCKER)


class _GenericBuild(_BuildStrategy):
    def build(self, config: BuildConfig, timeout: int) -> BuildResult:
        cmd = config.extra_args.get("build_command", "make build")
        return self._run(cmd, config.project_path, timeout, Language.GENERIC)


_STRATEGIES: Dict[Language, _BuildStrategy] = {
    Language.PYTHON: _PythonBuild(),
    Language.NODEJS: _NodeBuild(),
    Language.GO: _GoBuild(),
    Language.JAVA: _JavaBuild(),
    Language.DOCKER: _DockerBuild(),
    Language.GENERIC: _GenericBuild(),
}


# ---------------------------------------------------------------------------
# BuildEngine
# ---------------------------------------------------------------------------

class BuildEngine:
    """
    Orchestrate multi-language build pipelines for the Amosclaud Platform.

    Usage::

        engine = BuildEngine()
        config = BuildConfig(
            project_path="/path/to/project",
            language=Language.PYTHON,
        )
        result = engine.build(config)
        print(result.summary())
    """

    def __init__(self, timeout: int = 600) -> None:
        self.timeout = timeout
        self._history: List[BuildResult] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, config: BuildConfig) -> BuildResult:
        """Run a full build for *config*, including pre/post commands."""
        logger.info(
            "Building '%s' (%s, env=%s)",
            config.project_path,
            config.language.value,
            config.environment,
        )

        # Pre-build
        for cmd in config.pre_build_commands:
            ok = self._run_hook(cmd, config.project_path)
            if not ok:
                result = BuildResult(
                    success=False,
                    language=config.language,
                    duration_seconds=0.0,
                    log=f"Pre-build command failed: {cmd}",
                    error=f"Pre-build command failed: {cmd}",
                )
                self._history.append(result)
                return result

        # Ensure output directory exists
        out_dir = Path(config.project_path) / config.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        # Main build
        strategy = _STRATEGIES.get(config.language, _STRATEGIES[Language.GENERIC])
        result = strategy.build(config, self.timeout)

        # Collect artifacts
        if result.success:
            result.artifacts = self._collect_artifacts(out_dir)

        # Post-build
        if result.success:
            for cmd in config.post_build_commands:
                ok = self._run_hook(cmd, config.project_path)
                if not ok:
                    logger.warning("Post-build command failed: %s", cmd)

        self._history.append(result)
        status = "succeeded" if result.success else "failed"
        logger.info("Build %s in %.1fs", status, result.duration_seconds)
        return result

    def clean(self, config: BuildConfig) -> bool:
        """Remove the output directory for *config*."""
        out_dir = Path(config.project_path) / config.output_dir
        try:
            if out_dir.exists():
                shutil.rmtree(out_dir)
                logger.info("Cleaned build directory: %s", out_dir)
            return True
        except Exception as exc:
            logger.error("Clean failed: %s", exc)
            return False

    def detect_language(self, project_path: str) -> Language:
        """
        Heuristically detect the primary language of a project.

        Checks for well-known indicator files in order of specificity.
        """
        path = Path(project_path)
        indicators: List[tuple[str, Language]] = [
            ("Dockerfile", Language.DOCKER),
            ("pom.xml", Language.JAVA),
            ("go.mod", Language.GO),
            ("package.json", Language.NODEJS),
            ("setup.py", Language.PYTHON),
            ("setup.cfg", Language.PYTHON),
            ("pyproject.toml", Language.PYTHON),
        ]
        for filename, lang in indicators:
            if (path / filename).exists():
                logger.debug("Detected language '%s' via '%s'", lang.value, filename)
                return lang
        return Language.GENERIC

    def get_build_history(self) -> List[BuildResult]:
        """Return all build results from this session."""
        return list(self._history)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_hook(self, cmd: str, cwd: str) -> bool:
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=cwd,
            )
            return proc.returncode == 0
        except Exception as exc:
            logger.error("Hook command failed: %s — %s", cmd, exc)
            return False

    def _collect_artifacts(self, out_dir: Path) -> List[BuildArtifact]:
        artifacts: List[BuildArtifact] = []
        if not out_dir.exists():
            return artifacts
        for item in out_dir.rglob("*"):
            if item.is_file():
                try:
                    size = item.stat().st_size
                    artifacts.append(
                        BuildArtifact(
                            name=item.name,
                            path=str(item),
                            size_bytes=size,
                            artifact_type=item.suffix.lstrip(".") or "binary",
                        )
                    )
                except OSError:
                    pass
        return artifacts
