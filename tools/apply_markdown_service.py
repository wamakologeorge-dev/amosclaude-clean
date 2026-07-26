"""Apply the one-time Amosclaud Markdown service integration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected one marker in {relative}, found {count}: {old[:80]!r}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


replace_once(
    "amoscloud_ai/api/routes/repositories.py",
    "import threading\nfrom datetime import datetime, timezone\n",
    "import threading\nfrom collections import Counter\nfrom datetime import datetime, timezone\n",
)

replace_once(
    "amoscloud_ai/api/routes/repositories.py",
    "from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session\n",
    "from amoscloud_ai.api.routes.auth import DB_PATH, get_user_from_session\n"
    "from amoscloud_ai.markdown_service import render_markdown_document\n",
)

replace_once(
    "amoscloud_ai/api/routes/repositories.py",
    "_LOCKS_GUARD = threading.Lock()\n",
    """_LOCKS_GUARD = threading.Lock()
_MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
_INLINE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
}
_LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".php": "PHP",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".sql": "SQL",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".amcl": "Amosclaud Language",
}
""",
)

helpers_and_routes = r'''

def _repository_files(root: Path) -> list[Path]:
    """Return working-tree files without exposing Git's private storage."""
    return [
        item
        for item in root.rglob("*")
        if item.is_file() and ".git" not in item.relative_to(root).parts
    ]


def _is_markdown_path(path: Path) -> bool:
    return path.suffix.casefold() in _MARKDOWN_SUFFIXES or path.name.casefold() in {
        "readme",
        "license",
        "contributing",
        "security",
        "code_of_conduct",
    }


def _language_summary(root: Path, files: list[Path]) -> list[dict]:
    measured: Counter[str] = Counter()
    for item in files:
        language = _LANGUAGE_BY_SUFFIX.get(item.suffix.casefold())
        if not language and item.name.casefold() in {"dockerfile", "containerfile"}:
            language = "Dockerfile"
        if language:
            measured[language] += max(item.stat().st_size, 1)
    total = sum(measured.values())
    if not total:
        return []
    return [
        {
            "name": language,
            "bytes": size,
            "percentage": round((size / total) * 100, 2),
        }
        for language, size in measured.most_common()
    ]


def _root_file_lookup(root: Path, files: list[Path]) -> dict[str, str]:
    return {
        item.name.casefold(): item.relative_to(root).as_posix()
        for item in files
        if item.parent == root
    }


def _first_root_file(lookup: dict[str, str], *names: str) -> str | None:
    for name in names:
        if name.casefold() in lookup:
            return lookup[name.casefold()]
    return None


@router.get("/{repository_id}/overview")
def repository_overview(
    repository_id: int,
    branch: str = Query("main"),
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Return real repository facts for the workspace details sidebar."""
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        root = _repo_path(repository_id)
        files = _repository_files(root)
        lookup = _root_file_lookup(root, files)
        license_path = _first_root_file(
            lookup,
            "LICENSE",
            "LICENSE.md",
            "LICENSE.txt",
            "COPYING",
            "COPYING.md",
        )
        return {
            "branch": branch,
            "branch_count": len(repo.heads),
            "tag_count": len(repo.tags),
            "commit_count": sum(1 for _ in repo.iter_commits(branch)),
            "file_count": len(files),
            "repository_size": sum(item.stat().st_size for item in files),
            "languages": _language_summary(root, files),
            "license_label": "License" if license_path else None,
            "features": {
                "license": license_path,
                "code_of_conduct": _first_root_file(
                    lookup,
                    "CODE_OF_CONDUCT.md",
                    "CODE-OF-CONDUCT.md",
                    "CODE_OF_CONDUCT.txt",
                ),
                "contributing": _first_root_file(
                    lookup,
                    "CONTRIBUTING.md",
                    "CONTRIBUTING.txt",
                ),
                "security_policy": _first_root_file(
                    lookup,
                    "SECURITY.md",
                    "SECURITY.txt",
                ),
            },
        }


@router.get("/{repository_id}/markdown")
def render_repository_markdown(
    repository_id: int,
    path: str,
    branch: str = Query("main"),
    user: sqlite3.Row = Depends(_current_user),
) -> dict:
    """Render one repository Markdown file through Amosclaud's safe service."""
    relative = _safe_relative(path)
    if not _is_markdown_path(relative):
        raise HTTPException(status_code=415, detail="This file is not supported Markdown")
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        target = _repo_path(repository_id) / relative
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Markdown file not found")
        try:
            source = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Markdown must be UTF-8 text") from exc
        try:
            document = render_markdown_document(
                source,
                repository_id=repository_id,
                branch=branch,
                source_path=relative.as_posix(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        return {
            "path": relative.as_posix(),
            "branch": branch,
            "html": document.html,
            "outline": list(document.outline),
            "source_sha256": document.source_sha256,
        }


@router.get("/{repository_id}/raw")
def read_repository_media(
    repository_id: int,
    path: str,
    branch: str = Query("main"),
    user: sqlite3.Row = Depends(_current_user),
) -> Response:
    """Serve only safe inline image formats referenced by repository Markdown."""
    relative = _safe_relative(path)
    media_type = _INLINE_MEDIA_TYPES.get(relative.suffix.casefold())
    if not media_type:
        raise HTTPException(status_code=415, detail="Inline media type is not allowed")
    with _repo_lock(repository_id), _db() as db:
        _access(db, repository_id, user["id"])
        repo = _open(repository_id)
        _checkout(repo, branch)
        target = _repo_path(repository_id) / relative
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Media file not found")
        if target.stat().st_size > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Inline media exceeds the 10 MB limit")
        return Response(
            content=target.read_bytes(),
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=300",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )


'''

replace_once(
    "amoscloud_ai/api/routes/repositories.py",
    '@router.get("/{repository_id}/tree")\n',
    helpers_and_routes + '@router.get("/{repository_id}/tree")\n',
)

replace_once(
    "requirements.txt",
    "jinja2>=3.1.6\n",
    "jinja2>=3.1.6\nbleach>=6.1,<7\nmarkdown-it-py>=3,<5\nmdit-py-plugins>=0.4,<1\n",
)

replace_once(
    "Dockerfile",
    '        "jinja2>=3.1.3" \\\n',
    '        "jinja2>=3.1.3" \\\n'
    '        "bleach>=6.1,<7" \\\n'
    '        "markdown-it-py>=3,<5" \\\n'
    '        "mdit-py-plugins>=0.4,<1" \\\n',
)

replace_once(
    "web/workspace.html",
    '  <link rel="stylesheet" href="/static/editor-experience.css" />\n',
    '  <link rel="stylesheet" href="/static/editor-experience.css" />\n'
    '  <link rel="stylesheet" href="/static/markdown-service.css" />\n',
)

replace_once(
    "web/workspace.html",
    '<script src="/static/highlight.js"></script><script src="/static/workspace.js"></script>',
    '<script src="/static/highlight.js"></script><script src="/static/workspace.js"></script><script src="/static/markdown-service.js"></script>',
)
