"""
PlatformAPI — FastAPI REST interface for the Amosclaud Platform.

Exposes endpoints for:
  /platform/projects   — software creation
  /platform/build      — build engine
  /platform/tools      — developer tools quality checks
  /platform/ai         — AI assistant (code review, generation, docs)
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.platform.software_creator import (
    ProjectConfig,
    ProjectType,
    SoftwareCreator,
)
from src.platform.build_engine import BuildConfig, BuildEngine, Language
from src.platform.developer_tools import DeveloperTools
from src.platform.ai_assistant import AIAssistant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/platform", tags=["Amosclaud Platform"])

# Shared singletons — one per worker process.
_creator = SoftwareCreator()
_build_engine = BuildEngine()
_dev_tools = DeveloperTools()
_ai_assistant = AIAssistant()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str = Field(..., description="Project name (slug, no spaces)")
    project_type: str = Field(..., description="One of: " + ", ".join(pt.value for pt in ProjectType))
    language: str = Field("python", description="Primary language")
    description: str = Field("", description="Short project description")
    author: str = Field("", description="Author name")
    version: str = Field("0.1.0", description="Initial version")
    output_dir: str = Field(".", description="Where to create the project folder")
    features: List[str] = Field(default_factory=list)


class BuildRequest(BaseModel):
    project_path: str = Field(..., description="Absolute path to the project to build")
    language: Optional[str] = Field(None, description="Language override; auto-detected if omitted")
    environment: str = Field("production", description="Target environment")
    output_dir: str = Field("dist", description="Build output directory")
    docker_tag: Optional[str] = Field(None)
    pre_build_commands: List[str] = Field(default_factory=list)
    post_build_commands: List[str] = Field(default_factory=list)


class QualityCheckRequest(BaseModel):
    target: Optional[str] = Field(None, description="Path to check; defaults to project root")
    linters: bool = True
    formatters: bool = True
    tests: bool = True


class ReviewRequest(BaseModel):
    file_path: str = Field(..., description="Path to the file to review")


class GenerateFunctionRequest(BaseModel):
    name: str
    description: str
    language: str = "python"
    params: List[Dict[str, str]] = Field(default_factory=list)
    return_type: str = "None"


class GenerateClassRequest(BaseModel):
    name: str
    description: str
    methods: List[str] = Field(default_factory=list)
    language: str = "python"


class GenerateTestsRequest(BaseModel):
    file_path: str
    framework: str = "pytest"


class GenerateDocsRequest(BaseModel):
    file_path: str


# ---------------------------------------------------------------------------
# Platform info
# ---------------------------------------------------------------------------

@router.get("/", summary="Platform overview")
def platform_info() -> Dict[str, Any]:
    return {
        "platform": "Amosclaud Platform",
        "version": "1.0.0",
        "description": "Software creation, developer tools, and AI-powered building with Amosclaud-AI",
        "features": [
            "Project scaffolding",
            "Multi-language build automation",
            "Linting, formatting & testing",
            "AI code review",
            "AI code generation",
            "AI documentation",
        ],
        "endpoints": {
            "projects": "/platform/projects",
            "build": "/platform/build",
            "tools": "/platform/tools/quality-check",
            "ai": "/platform/ai",
        },
    }


# ---------------------------------------------------------------------------
# Software creation
# ---------------------------------------------------------------------------

@router.get("/projects/templates", summary="List available project templates")
def list_templates() -> Dict[str, Any]:
    return {"templates": _creator.list_templates()}


@router.post("/projects/create", summary="Scaffold a new project", status_code=status.HTTP_201_CREATED)
def create_project(req: CreateProjectRequest) -> Dict[str, Any]:
    try:
        project_type = ProjectType(req.project_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown project_type '{req.project_type}'. Valid values: {_creator.list_templates()}",
        )

    config = ProjectConfig(
        name=req.name,
        project_type=project_type,
        language=req.language,
        description=req.description,
        author=req.author,
        version=req.version,
        output_dir=req.output_dir,
        features=req.features,
    )
    result = _creator.create_project(config)
    if not result.success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.message)

    return {
        "success": True,
        "project_path": result.project_path,
        "files_created": result.files_created,
        "message": result.message,
    }


@router.get("/projects/history", summary="List previously created projects")
def project_history() -> Dict[str, Any]:
    history = _creator.get_creation_history()
    return {
        "total": len(history),
        "projects": [
            {
                "project_path": r.project_path,
                "files_created": len(r.files_created),
                "created_at": r.created_at.isoformat(),
                "message": r.message,
            }
            for r in history
        ],
    }


# ---------------------------------------------------------------------------
# Build engine
# ---------------------------------------------------------------------------

@router.post("/build", summary="Build a project")
def build_project(req: BuildRequest) -> Dict[str, Any]:
    if req.language:
        try:
            lang = Language(req.language)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown language '{req.language}'",
            )
    else:
        lang = _build_engine.detect_language(req.project_path)

    config = BuildConfig(
        project_path=req.project_path,
        language=lang,
        environment=req.environment,
        output_dir=req.output_dir,
        docker_tag=req.docker_tag,
        pre_build_commands=req.pre_build_commands,
        post_build_commands=req.post_build_commands,
    )
    result = _build_engine.build(config)
    return result.summary()


@router.get("/build/history", summary="List build history")
def build_history() -> Dict[str, Any]:
    history = _build_engine.get_build_history()
    return {
        "total": len(history),
        "builds": [r.summary() for r in history],
    }


# ---------------------------------------------------------------------------
# Developer tools
# ---------------------------------------------------------------------------

@router.post("/tools/quality-check", summary="Run full quality check")
def quality_check(req: QualityCheckRequest) -> Dict[str, Any]:
    report = _dev_tools.run_quality_check(
        target=req.target,
        linters=req.linters,
        formatters=req.formatters,
        tests=req.tests,
    )
    return {
        **report.summary(),
        "results": [
            {
                "tool": r.tool,
                "status": r.status.value,
                "duration_seconds": round(r.duration_seconds, 2),
                "issues_count": len(r.issues),
            }
            for r in report.results
        ],
    }


@router.get("/tools/available", summary="List available developer tools")
def available_tools() -> Dict[str, Any]:
    return {"tools": _dev_tools.list_available_tools()}


# ---------------------------------------------------------------------------
# AI assistant
# ---------------------------------------------------------------------------

@router.post("/ai/review", summary="AI code review for a file")
def ai_review(req: ReviewRequest) -> Dict[str, Any]:
    result = _ai_assistant.review_file(req.file_path)
    return {
        "file_path": result.file_path,
        "overall_score": result.overall_score,
        "summary": result.summary,
        "has_issues": result.has_issues,
        "suggestions": [s.to_dict() for s in result.suggestions],
    }


@router.post("/ai/generate/function", summary="Generate a function stub")
def generate_function(req: GenerateFunctionRequest) -> Dict[str, Any]:
    snippet = _ai_assistant.generate_function(
        name=req.name,
        description=req.description,
        language=req.language,
        params=req.params,
        return_type=req.return_type,
    )
    return {"language": req.language, "code": snippet}


@router.post("/ai/generate/class", summary="Generate a class stub")
def generate_class(req: GenerateClassRequest) -> Dict[str, Any]:
    snippet = _ai_assistant.generate_class(
        name=req.name,
        description=req.description,
        methods=req.methods,
        language=req.language,
    )
    return {"language": req.language, "code": snippet}


@router.post("/ai/generate/tests", summary="Generate unit tests for a file")
def generate_tests(req: GenerateTestsRequest) -> Dict[str, Any]:
    snippet = _ai_assistant.generate_tests(
        file_path=req.file_path,
        framework=req.framework,
    )
    return {"framework": req.framework, "code": snippet}


@router.post("/ai/generate/docs", summary="Generate Markdown documentation for a file")
def generate_docs(req: GenerateDocsRequest) -> Dict[str, Any]:
    docs = _ai_assistant.generate_docs(req.file_path)
    return {"file_path": req.file_path, "docs": docs}


@router.post("/ai/refactor", summary="Get refactoring suggestions for a file")
def suggest_refactoring(req: ReviewRequest) -> Dict[str, Any]:
    suggestions = _ai_assistant.suggest_refactoring(req.file_path)
    return {
        "file_path": req.file_path,
        "suggestions": [s.to_dict() for s in suggestions],
    }


@router.get("/ai/history", summary="AI assistant operation history")
def ai_history() -> Dict[str, Any]:
    return {"history": _ai_assistant.get_history()}
