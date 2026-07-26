"""Apply the temporary repository-root/Git initialization correction."""

from pathlib import Path


TARGET = Path("amoscloud_ai/api/routes/repositories.py")

source = TARGET.read_text(encoding="utf-8")

cached_root = 'REPOSITORY_ROOT_RESOLVED = REPOSITORY_ROOT.resolve()\n'
if source.count(cached_root) != 1:
    raise SystemExit("Expected exactly one cached repository root declaration")
source = source.replace(cached_root, "", 1)

old_repo_path = '''def _repo_path(repository_id: int) -> Path:
    safe_repository_id = _safe_repository_id(repository_id)
    candidate = (REPOSITORY_ROOT_RESOLVED / str(safe_repository_id)).absolute()
    try:
        candidate.relative_to(REPOSITORY_ROOT_RESOLVED)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid repository path") from exc
    return candidate
'''
new_repo_path = '''def _repository_root() -> Path:
    """Resolve the configured repository root at call time.

    Tests and worker processes may override ``REPOSITORY_ROOT`` after module
    import. Resolving it dynamically prevents writes from escaping an isolated
    test directory or continuing to use stale production storage.
    """

    return REPOSITORY_ROOT.expanduser().resolve()


def _repo_path(repository_id: int) -> Path:
    safe_repository_id = _safe_repository_id(repository_id)
    repository_root = _repository_root()
    candidate = (repository_root / str(safe_repository_id)).resolve()
    try:
        candidate.relative_to(repository_root)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid repository path") from exc
    return candidate
'''
if source.count(old_repo_path) != 1:
    raise SystemExit("Expected exactly one repository path helper")
source = source.replace(old_repo_path, new_repo_path, 1)

old_open = '''def _open(repository_id: int) -> Repo:
    try:
        return Repo(_repo_path(repository_id))
    except (InvalidGitRepositoryError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Repository storage is damaged") from exc
'''
new_open = '''def _open(repository_id: int) -> Repo:
    try:
        return Repo(_repo_path(repository_id))
    except (InvalidGitRepositoryError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Repository storage is damaged") from exc


def _initialize_repository(path: Path) -> Repo:
    """Create a non-bare Git repository and prove its metadata exists."""

    repo = Repo.init(path, initial_branch="main")
    if not (path / ".git").is_dir():
        raise RuntimeError(f"Git initialization did not create metadata at {path}")
    return repo
'''
if source.count(old_open) != 1:
    raise SystemExit("Expected exactly one repository open helper")
source = source.replace(old_open, new_open, 1)

old_init = '            repo = Repo.init(path, initial_branch="main")\n'
new_init = '            repo = _initialize_repository(path)\n'
if source.count(old_init) != 1:
    raise SystemExit("Expected exactly one repository initialization call")
source = source.replace(old_init, new_init, 1)

if "REPOSITORY_ROOT_RESOLVED" in source:
    raise SystemExit("Stale repository root cache remains")

TARGET.write_text(source, encoding="utf-8")
