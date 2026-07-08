"""
PlatformCLI — Command-line interface for the Amosclaud Platform.

Sub-commands:
  create    — scaffold a new software project
  build     — build a project
  check     — run quality checks (lint, format, test)
  review    — AI code review
  generate  — AI code / test / docs generation
  serve     — launch the platform API server
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy imports so the CLI can display --help without importing heavy deps
# ---------------------------------------------------------------------------

def _get_creator():
    from src.platform.software_creator import SoftwareCreator
    return SoftwareCreator()


def _get_build_engine():
    from src.platform.build_engine import BuildEngine
    return BuildEngine()


def _get_dev_tools(project_root: str = "."):
    from src.platform.developer_tools import DeveloperTools
    return DeveloperTools(project_root=project_root)


def _get_ai_assistant():
    from src.platform.ai_assistant import AIAssistant
    return AIAssistant()


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> int:
    from src.platform.software_creator import ProjectConfig, ProjectType

    try:
        project_type = ProjectType(args.type)
    except ValueError:
        print(f"Error: unknown project type '{args.type}'.", file=sys.stderr)
        print("Available types: " + ", ".join(pt.value for pt in ProjectType))
        return 1

    config = ProjectConfig(
        name=args.name,
        project_type=project_type,
        language=args.language,
        description=args.description,
        author=args.author,
        version=args.version,
        output_dir=args.output_dir,
    )
    result = _get_creator().create_project(config)

    if result.success:
        print(f"✅  Project '{args.name}' created at: {result.project_path}")
        print(f"    Files created: {len(result.files_created)}")
        for f in result.files_created:
            print(f"      • {f}")
        return 0
    else:
        print(f"❌  Failed to create project: {result.message}", file=sys.stderr)
        return 1


def cmd_build(args: argparse.Namespace) -> int:
    from src.platform.build_engine import BuildConfig, BuildEngine, Language

    engine = _get_build_engine()
    project_path = str(Path(args.path).resolve())

    if args.language:
        try:
            lang = Language(args.language)
        except ValueError:
            print(f"Error: unknown language '{args.language}'.", file=sys.stderr)
            return 1
    else:
        lang = engine.detect_language(project_path)
        print(f"Auto-detected language: {lang.value}")

    config = BuildConfig(
        project_path=project_path,
        language=lang,
        environment=args.environment,
        output_dir=args.output_dir,
        docker_tag=getattr(args, "docker_tag", None),
    )
    result = engine.build(config)
    summary = result.summary()

    if result.success:
        print(f"✅  Build succeeded in {summary['duration_seconds']:.1f}s")
        if summary["artifacts"]:
            print("    Artifacts:")
            for a in summary["artifacts"]:
                print(f"      • {a}")
        return 0
    else:
        print(f"❌  Build failed: {summary['error']}", file=sys.stderr)
        return 1


def cmd_check(args: argparse.Namespace) -> int:
    tools = _get_dev_tools(args.path)
    report = tools.run_quality_check(
        target=args.path if args.path != "." else None,
        linters=not args.no_lint,
        formatters=not args.no_format,
        tests=not args.no_tests,
    )
    summary = report.summary()

    status_icon = "✅" if summary["overall_passed"] else "❌"
    print(f"{status_icon}  Quality check {'PASSED' if summary['overall_passed'] else 'FAILED'}")
    print(f"    Tools run : {summary['tools_run']}")
    print(f"    Passed    : {summary['passed']}")
    print(f"    Failed    : {summary['failed']}")
    print(f"    Skipped   : {summary['skipped']}")

    if args.verbose:
        for r in report.results:
            icon = "✅" if r.passed else ("⏭ " if r.status.value == "skipped" else "❌")
            print(f"\n  {icon} {r.tool} ({r.duration_seconds:.1f}s)")
            if r.output:
                for line in r.output.splitlines()[:20]:
                    print(f"     {line}")

    return 0 if summary["overall_passed"] else 1


def cmd_review(args: argparse.Namespace) -> int:
    assistant = _get_ai_assistant()
    result = assistant.review_file(args.file)

    icon = "✅" if not result.has_issues else "⚠️ "
    print(f"{icon}  Code review for: {args.file}")
    print(f"    Score  : {result.overall_score}/10")
    print(f"    Summary: {result.summary}")

    if result.suggestions:
        print("\n  Suggestions:")
        for s in result.suggestions:
            print(f"    [{s.suggestion_type.value.upper()}] {s.title}")
            print(f"      {s.description}")
    else:
        print("  No suggestions — looks good!")

    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    assistant = _get_ai_assistant()

    if args.generate_command == "function":
        code = assistant.generate_function(
            name=args.name,
            description=args.description,
            language=args.language,
            return_type=args.return_type,
        )
        print(code)

    elif args.generate_command == "class":
        methods = args.methods.split(",") if args.methods else []
        code = assistant.generate_class(
            name=args.name,
            description=args.description,
            methods=methods,
            language=args.language,
        )
        print(code)

    elif args.generate_command == "tests":
        code = assistant.generate_tests(
            file_path=args.file,
            framework=args.framework,
        )
        if args.output:
            Path(args.output).write_text(code, encoding="utf-8")
            print(f"Tests written to: {args.output}")
        else:
            print(code)

    elif args.generate_command == "docs":
        docs = assistant.generate_docs(args.file)
        if args.output:
            Path(args.output).write_text(docs, encoding="utf-8")
            print(f"Docs written to: {args.output}")
        else:
            print(docs)

    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is required to run the platform server.", file=sys.stderr)
        print("Install it with: pip install uvicorn[standard]")
        return 1

    try:
        uvicorn.run(
            "src.platform.platform_api:router",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level=args.log_level,
        )
    except Exception as exc:
        print(f"Error: failed to start server — {exc}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    from src.platform.software_creator import ProjectType
    from src.platform.build_engine import Language

    parser = argparse.ArgumentParser(
        prog="amosclaud-platform",
        description="Amosclaud Platform — software creation, developer tools, and AI-powered building",
    )
    parser.add_argument("--version", action="version", version="1.0.0")
    sub = parser.add_subparsers(dest="command", required=True)

    # ── create ──────────────────────────────────────────────────────────────
    p_create = sub.add_parser("create", help="Scaffold a new software project")
    p_create.add_argument("name", help="Project name")
    p_create.add_argument(
        "--type",
        default="web_api",
        choices=[pt.value for pt in ProjectType],
        help="Project type (default: web_api)",
    )
    p_create.add_argument("--language", default="python", help="Primary language")
    p_create.add_argument("--description", default="", help="Short description")
    p_create.add_argument("--author", default="", help="Author name")
    p_create.add_argument("--project-version", dest="version", default="0.1.0")
    p_create.add_argument("--output-dir", default=".", help="Parent directory for the project")

    # ── build ────────────────────────────────────────────────────────────────
    p_build = sub.add_parser("build", help="Build a project")
    p_build.add_argument("path", nargs="?", default=".", help="Project path (default: .)")
    p_build.add_argument(
        "--language",
        choices=[l.value for l in Language],
        default=None,
        help="Language override (auto-detected if omitted)",
    )
    p_build.add_argument("--environment", default="production")
    p_build.add_argument("--output-dir", default="dist")
    p_build.add_argument("--docker-tag", default=None)

    # ── check ────────────────────────────────────────────────────────────────
    p_check = sub.add_parser("check", help="Run quality checks")
    p_check.add_argument("path", nargs="?", default=".", help="Target path (default: .)")
    p_check.add_argument("--no-lint", action="store_true")
    p_check.add_argument("--no-format", action="store_true")
    p_check.add_argument("--no-tests", action="store_true")
    p_check.add_argument("-v", "--verbose", action="store_true")

    # ── review ───────────────────────────────────────────────────────────────
    p_review = sub.add_parser("review", help="AI code review for a file")
    p_review.add_argument("file", help="File to review")

    # ── generate ─────────────────────────────────────────────────────────────
    p_gen = sub.add_parser("generate", help="AI-powered code generation")
    gen_sub = p_gen.add_subparsers(dest="generate_command", required=True)

    g_func = gen_sub.add_parser("function", help="Generate a function stub")
    g_func.add_argument("name", help="Function name")
    g_func.add_argument("description", help="What the function should do")
    g_func.add_argument("--language", default="python")
    g_func.add_argument("--return-type", default="None")

    g_cls = gen_sub.add_parser("class", help="Generate a class stub")
    g_cls.add_argument("name", help="Class name")
    g_cls.add_argument("description", help="What the class represents")
    g_cls.add_argument("--methods", default="", help="Comma-separated method names")
    g_cls.add_argument("--language", default="python")

    g_tests = gen_sub.add_parser("tests", help="Generate unit tests for a file")
    g_tests.add_argument("file", help="Source file to generate tests for")
    g_tests.add_argument("--framework", default="pytest")
    g_tests.add_argument("--output", default=None, help="Write tests to this file")

    g_docs = gen_sub.add_parser("docs", help="Generate Markdown docs for a file")
    g_docs.add_argument("file", help="Source file to document")
    g_docs.add_argument("--output", default=None, help="Write docs to this file")

    # ── serve ────────────────────────────────────────────────────────────────
    p_serve = sub.add_parser("serve", help="Launch the Amosclaud Platform API server")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8001)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.add_argument("--log-level", default="info")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "create": cmd_create,
        "build": cmd_build,
        "check": cmd_check,
        "review": cmd_review,
        "generate": cmd_generate,
        "serve": cmd_serve,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
