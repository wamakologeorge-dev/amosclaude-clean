from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from amoscloud_ai.api.routes.auth import get_user_from_session
from amoscloud_ai.isolated_runner import run_in_isolated_container
from amoscloud_ai.task_dispatch import dispatch_task


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("AMOSCLAUD_DASHBOARD_DATA", BASE_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
DB_PATH = DATA_DIR / "dashboard.db"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
LOGIN_URL = os.getenv("AMOSCLAUD_AUTH_LOGIN_URL", "/login")

for directory in (DATA_DIR, PROJECTS_DIR, ARTIFACTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def _validate_production_configuration() -> None:
    if ENVIRONMENT not in {"production", "prod"}:
        return
    missing: list[str] = []
    if not os.getenv("AMOSCLAUD_DASHBOARD_KEY", "").strip():
        missing.append("AMOSCLAUD_DASHBOARD_KEY")
    if not os.getenv("AMOSCLAUD_RUNNER_IMAGE", "").strip():
        missing.append("AMOSCLAUD_RUNNER_IMAGE")
    if not (
        os.getenv("CELERY_BROKER_URL", "").strip()
        or os.getenv("REDIS_URL", "").strip()
    ):
        missing.append("CELERY_BROKER_URL or REDIS_URL")
    public_url = os.getenv("AMOSCLAUD_PUBLIC_URL", "").strip().lower()
    if not public_url.startswith("https://"):
        missing.append("AMOSCLAUD_PUBLIC_URL=https://...")
    if missing:
        raise RuntimeError(
            "Workflow dashboard production configuration is incomplete: "
            + ", ".join(missing)
        )


_validate_production_configuration()


def _fernet() -> Fernet:
    configured = os.getenv("AMOSCLAUD_DASHBOARD_KEY", "").strip()
    if configured:
        try:
            return Fernet(configured.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "AMOSCLAUD_DASHBOARD_KEY must be a valid Fernet key."
            ) from exc

    if ENVIRONMENT in {"production", "prod"}:
        raise RuntimeError("AMOSCLAUD_DASHBOARD_KEY is required in production")

    key_path = DATA_DIR / ".dashboard.key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes().strip())


FERNET = _fernet()
app = FastAPI(title="Amosclaud Workflow Dashboard", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_columns(db: sqlite3.Connection, table: str) -> set[str]:
    allowed = {"projects", "variables", "runs", "artifacts"}
    if table not in allowed:
        raise ValueError("Unknown dashboard table")
    return {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}


def _ensure_owner_column(db: sqlite3.Connection, table: str) -> None:
    if "owner_user_id" not in _table_columns(db, table):
        db.execute(
            f"ALTER TABLE {table} "
            "ADD COLUMN owner_user_id INTEGER NOT NULL DEFAULT 0"
        )


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                repository_url TEXT NOT NULL DEFAULT '',
                root_path TEXT NOT NULL DEFAULT '.',
                build_command TEXT NOT NULL DEFAULT '',
                start_command TEXT NOT NULL DEFAULT '',
                output_path TEXT NOT NULL DEFAULT '',
                domain TEXT NOT NULL DEFAULT '',
                domain_token TEXT NOT NULL DEFAULT '',
                domain_verified INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS variables (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                encrypted_value BLOB NOT NULL,
                is_secret INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                UNIQUE(project_id, name),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                objective TEXT NOT NULL DEFAULT '',
                started_at INTEGER NOT NULL,
                finished_at INTEGER,
                exit_code INTEGER,
                log_path TEXT NOT NULL DEFAULT '',
                preview_url TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                name TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                created_at INTEGER NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            """
        )
        for table in ("projects", "variables", "runs", "artifacts"):
            _ensure_owner_column(db, table)
            db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_owner "
                f"ON {table}(owner_user_id)"
            )

        legacy_owner = os.getenv("AMOSCLAUD_LEGACY_OWNER_USER_ID", "").strip()
        if legacy_owner.isdigit() and int(legacy_owner) > 0:
            owner_id = int(legacy_owner)
            for table in ("projects", "variables", "runs", "artifacts"):
                db.execute(
                    f"UPDATE {table} SET owner_user_id=? WHERE owner_user_id=0",
                    (owner_id,),
                )
        db.commit()


init_db()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    repository_url: str = Field(default="", max_length=2_000)
    root_path: str = Field(default=".", max_length=500)
    build_command: str = Field(default="", max_length=4_096)
    start_command: str = Field(default="", max_length=4_096)
    output_path: str = Field(default="", max_length=500)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    repository_url: str | None = Field(default=None, max_length=2_000)
    root_path: str | None = Field(default=None, max_length=500)
    build_command: str | None = Field(default=None, max_length=4_096)
    start_command: str | None = Field(default=None, max_length=4_096)
    output_path: str | None = Field(default=None, max_length=500)


class VariableInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: str = Field(max_length=32_768)
    is_secret: bool = True


class DomainInput(BaseModel):
    domain: str = Field(min_length=1, max_length=253)


class RunInput(BaseModel):
    objective: str = Field(default="Run agent workflow", max_length=2_000)


def require_user(request: Request) -> sqlite3.Row:
    user = get_user_from_session(request.cookies.get("amos_session"))
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _owner_id(user: sqlite3.Row) -> int:
    return int(user["id"])


def _project_row(
    db: sqlite3.Connection,
    project_id: str,
    owner_user_id: int,
) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM projects WHERE id=? AND owner_user_id=?",
        (project_id, owner_user_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return row


def _normalize_domain(value: str) -> str:
    """Validate a hostname in linear time without a backtracking expression."""

    domain = value.strip().lower().rstrip(".")
    if not domain or len(domain) > 253:
        raise HTTPException(400, "Enter a valid hostname")
    labels = domain.split(".")
    if len(labels) < 2:
        raise HTTPException(400, "Enter a valid hostname")
    for label in labels:
        if not 1 <= len(label) <= 63:
            raise HTTPException(400, "Enter a valid hostname")
        if label[0] == "-" or label[-1] == "-":
            raise HTTPException(400, "Enter a valid hostname")
        if not all(character.isalnum() or character == "-" for character in label):
            raise HTTPException(400, "Enter a valid hostname")
    if not labels[-1].isalpha() or len(labels[-1]) < 2:
        raise HTTPException(400, "Enter a valid hostname")
    return domain


def project_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "repository_url": row["repository_url"],
        "root_path": row["root_path"],
        "build_command": row["build_command"],
        "start_command": row["start_command"],
        "output_path": row["output_path"],
        "domain": row["domain"],
        "domain_verified": bool(row["domain_verified"]),
        "created_at": row["created_at"],
    }


def _public_run(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result.pop("owner_user_id", None)
    result.pop("log_path", None)
    return result


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> FileResponse | RedirectResponse:
    if not get_user_from_session(request.cookies.get("amos_session")):
        return RedirectResponse(LOGIN_URL, status_code=302)
    return FileResponse(BASE_DIR / "templates" / "dashboard.html")


@app.get("/api/projects")
async def list_projects(
    user: sqlite3.Row = Depends(require_user),
) -> list[dict[str, Any]]:
    owner = _owner_id(user)
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM projects WHERE owner_user_id=? ORDER BY created_at DESC",
            (owner,),
        ).fetchall()
    return [project_dict(row) for row in rows]


@app.post("/api/projects", status_code=201)
async def create_project(
    payload: ProjectCreate,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    owner = _owner_id(user)
    project_id = str(uuid.uuid4())
    now = int(time.time())
    with connect() as db:
        db.execute(
            """
            INSERT INTO projects(
                id, owner_user_id, name, repository_url, root_path,
                build_command, start_command, output_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                owner,
                payload.name,
                payload.repository_url,
                payload.root_path,
                payload.build_command,
                payload.start_command,
                payload.output_path,
                now,
            ),
        )
        db.commit()
    (PROJECTS_DIR / str(owner) / project_id).mkdir(parents=True, exist_ok=True)
    return await get_project(project_id, user)


@app.get("/api/projects/{project_id}")
async def get_project(
    project_id: str,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    owner = _owner_id(user)
    with connect() as db:
        row = _project_row(db, project_id, owner)
        variables = db.execute(
            """
            SELECT id, name, is_secret, created_at
            FROM variables
            WHERE project_id=? AND owner_user_id=?
            ORDER BY name
            """,
            (project_id, owner),
        ).fetchall()
        runs = db.execute(
            """
            SELECT * FROM runs
            WHERE project_id=? AND owner_user_id=?
            ORDER BY started_at DESC LIMIT 20
            """,
            (project_id, owner),
        ).fetchall()

    result = project_dict(row)
    result["variables"] = [
        {
            "id": variable["id"],
            "name": variable["name"],
            "is_secret": bool(variable["is_secret"]),
            "value": "••••••••",
            "created_at": variable["created_at"],
        }
        for variable in variables
    ]
    result["runs"] = [_public_run(run) for run in runs]
    return result


@app.patch("/api/projects/{project_id}")
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    owner = _owner_id(user)
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return await get_project(project_id, user)

    allowed = {
        "name",
        "repository_url",
        "root_path",
        "build_command",
        "start_command",
        "output_path",
    }
    updates = {key: value for key, value in updates.items() if key in allowed}
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [*updates.values(), project_id, owner]

    with connect() as db:
        cursor = db.execute(
            f"UPDATE projects SET {assignments} "
            "WHERE id=? AND owner_user_id=?",
            values,
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Project not found")
        db.commit()
    return await get_project(project_id, user)


@app.put("/api/projects/{project_id}/variables/{name}")
async def set_variable(
    project_id: str,
    name: str,
    payload: VariableInput,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, str]:
    owner = _owner_id(user)
    if name != payload.name:
        raise HTTPException(400, "Variable name mismatch")

    encrypted = FERNET.encrypt(payload.value.encode())
    with connect() as db:
        _project_row(db, project_id, owner)
        db.execute(
            """
            INSERT INTO variables(
                id, owner_user_id, project_id, name,
                encrypted_value, is_secret, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, name) DO UPDATE SET
                owner_user_id=excluded.owner_user_id,
                encrypted_value=excluded.encrypted_value,
                is_secret=excluded.is_secret,
                created_at=excluded.created_at
            """,
            (
                str(uuid.uuid4()),
                owner,
                project_id,
                payload.name,
                encrypted,
                int(payload.is_secret),
                int(time.time()),
            ),
        )
        db.commit()
    return {"status": "saved", "name": name}


@app.delete("/api/projects/{project_id}/variables/{name}", status_code=204)
async def delete_variable(
    project_id: str,
    name: str,
    user: sqlite3.Row = Depends(require_user),
) -> None:
    owner = _owner_id(user)
    with connect() as db:
        _project_row(db, project_id, owner)
        db.execute(
            "DELETE FROM variables "
            "WHERE project_id=? AND owner_user_id=? AND name=?",
            (project_id, owner, name),
        )
        db.commit()


@app.post("/api/projects/{project_id}/domain")
async def set_domain(
    project_id: str,
    payload: DomainInput,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    owner = _owner_id(user)
    domain = _normalize_domain(payload.domain)
    token = "amosclaud-verification=" + secrets.token_urlsafe(24)
    with connect() as db:
        cursor = db.execute(
            """
            UPDATE projects
            SET domain=?, domain_token=?, domain_verified=0
            WHERE id=? AND owner_user_id=?
            """,
            (domain, token, project_id, owner),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Project not found")
        db.commit()

    return {
        "domain": domain,
        "verified": False,
        "dns_record": {
            "type": "TXT",
            "name": f"_amosclaud.{domain}",
            "value": token,
        },
    }


@app.post("/api/projects/{project_id}/domain/verify")
async def verify_domain(
    project_id: str,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    owner = _owner_id(user)
    with connect() as db:
        row = db.execute(
            """
            SELECT domain, domain_token FROM projects
            WHERE id=? AND owner_user_id=?
            """,
            (project_id, owner),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    if not row["domain"]:
        raise HTTPException(400, "No domain is configured")

    try:
        import dns.resolver

        answers = dns.resolver.resolve(
            f"_amosclaud.{row['domain']}", "TXT", lifetime=8
        )
        values = {b"".join(answer.strings).decode() for answer in answers}
    except Exception:
        return {
            "verified": False,
            "message": "DNS verification is not ready. Please try again later.",
        }

    verified = row["domain_token"] in values
    if verified:
        with connect() as db:
            db.execute(
                """
                UPDATE projects SET domain_verified=1
                WHERE id=? AND owner_user_id=?
                """,
                (project_id, owner),
            )
            db.commit()
    return {
        "verified": verified,
        "message": (
            "Domain ownership verified."
            if verified
            else "TXT record was not found or does not match."
        ),
    }


def load_environment(project_id: str, owner_user_id: int) -> dict[str, str]:
    result: dict[str, str] = {}
    with connect() as db:
        rows = db.execute(
            """
            SELECT name, encrypted_value FROM variables
            WHERE project_id=? AND owner_user_id=?
            """,
            (project_id, owner_user_id),
        ).fetchall()
    for row in rows:
        try:
            result[row["name"]] = FERNET.decrypt(row["encrypted_value"]).decode()
        except InvalidToken as exc:
            raise RuntimeError("A stored project variable could not be decrypted") from exc
    return result


def resolve_within(base: Path, *parts: str) -> Path:
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise HTTPException(400, "Path escapes allowed directory") from exc
    return candidate


def _set_run_state(
    run_id: str,
    owner_user_id: int,
    *,
    status: str,
    exit_code: int | None = None,
    finished: bool = False,
) -> None:
    with connect() as db:
        db.execute(
            """
            UPDATE runs
            SET status=?, exit_code=?, finished_at=?
            WHERE id=? AND owner_user_id=?
            """,
            (
                status,
                exit_code,
                int(time.time()) if finished else None,
                run_id,
                owner_user_id,
            ),
        )
        db.commit()


def _register_artifact(
    run_id: str,
    owner_user_id: int,
    name: str,
    relative_path: str,
    media_type: str,
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO artifacts(
                id, owner_user_id, run_id, name,
                relative_path, media_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                owner_user_id,
                run_id,
                name,
                relative_path,
                media_type,
                int(time.time()),
            ),
        )
        db.commit()


def execute_queued_run(run_id: str, owner_user_id: int) -> str:
    """Worker-only execution entry point. Never call this from an API request."""

    with connect() as db:
        run = db.execute(
            "SELECT * FROM runs WHERE id=? AND owner_user_id=?",
            (run_id, owner_user_id),
        ).fetchone()
        if not run:
            raise RuntimeError("Queued run was not found")
        project = db.execute(
            "SELECT * FROM projects WHERE id=? AND owner_user_id=?",
            (run["project_id"], owner_user_id),
        ).fetchone()
        if not project:
            raise RuntimeError("Queued project was not found")

    run_dir = resolve_within(ARTIFACTS_DIR, str(owner_user_id), run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    project_root = resolve_within(
        PROJECTS_DIR,
        str(owner_user_id),
        str(project["id"]),
    )
    workspace = resolve_within(project_root, str(project["root_path"]))
    workspace.mkdir(parents=True, exist_ok=True)

    with connect() as db:
        db.execute(
            """
            UPDATE runs SET status='running', log_path=?
            WHERE id=? AND owner_user_id=?
            """,
            (str(log_path), run_id, owner_user_id),
        )
        db.commit()

    commands = [
        command
        for command in (project["build_command"], project["start_command"])
        if str(command).strip()
    ]
    if not commands:
        commands = ["python --version"]

    environment = load_environment(str(project["id"]), owner_user_id)
    environment.update(
        {
            "AMOSCLAUD_RUN_ID": run_id,
            "AMOSCLAUD_PROJECT_ID": str(project["id"]),
        }
    )
    status = "succeeded"
    exit_code = 0

    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"Objective: {run['objective']}\n")
            log.write("Executor: isolated container worker\n\n")
            for command in commands:
                log.write(f"$ {command}\n")
                result = run_in_isolated_container(
                    str(command),
                    workspace=workspace,
                    environment=environment,
                )
                log.write(result.output)
                log.write("\n")
                log.flush()
                exit_code = result.returncode
                if exit_code != 0:
                    status = "failed"
                    break
    except Exception as exc:
        status = "failed"
        exit_code = 1
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                "Runner stopped safely: "
                f"{type(exc).__name__}. See worker logs for operator details.\n"
            )

    _register_artifact(
        run_id,
        owner_user_id,
        "run.log",
        "run.log",
        "text/plain; charset=utf-8",
    )

    output_path = str(project["output_path"]).strip()
    if output_path and status == "succeeded":
        try:
            output = resolve_within(workspace, output_path)
        except HTTPException:
            status = "failed"
            exit_code = 1
            output = None
            with log_path.open("a", encoding="utf-8") as log:
                log.write("Output path escapes workspace.\n")
        if output is not None and output.exists():
            manifest = run_dir / "artifact-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "name": output.name,
                        "kind": "file" if output.is_file() else "directory",
                        "sha256": (
                            hashlib.sha256(output.read_bytes()).hexdigest()
                            if output.is_file()
                            else None
                        ),
                        "preview": "not-published",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            _register_artifact(
                run_id,
                owner_user_id,
                "artifact-manifest.json",
                "artifact-manifest.json",
                "application/json",
            )

    _set_run_state(
        run_id,
        owner_user_id,
        status=status,
        exit_code=exit_code,
        finished=True,
    )
    return status


@app.post("/api/projects/{project_id}/runs", status_code=202)
async def start_run(
    project_id: str,
    payload: RunInput,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    owner = _owner_id(user)
    try:
        uuid.UUID(project_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid project id") from exc

    with connect() as db:
        _project_row(db, project_id, owner)

    run_id = str(uuid.uuid4())
    started_at = int(time.time())
    with connect() as db:
        db.execute(
            """
            INSERT INTO runs(
                id, owner_user_id, project_id, status,
                objective, started_at, log_path
            ) VALUES (?, ?, ?, 'queued', ?, ?, '')
            """,
            (run_id, owner, project_id, payload.objective, started_at),
        )
        db.commit()

    try:
        from amoscloud_ai.dashboard_worker import run_dashboard_project

        dispatch_task(run_dashboard_project, run_id, owner)
    except Exception as exc:
        _set_run_state(
            run_id,
            owner,
            status="failed",
            exit_code=1,
            finished=True,
        )
        raise HTTPException(
            status_code=503,
            detail="The isolated worker queue is unavailable. The run was not executed.",
        ) from exc

    return await get_run(run_id, user)


@app.get("/api/runs/{run_id}")
async def get_run(
    run_id: str,
    user: sqlite3.Row = Depends(require_user),
) -> dict[str, Any]:
    owner = _owner_id(user)
    try:
        uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid run id") from exc

    with connect() as db:
        run = db.execute(
            "SELECT * FROM runs WHERE id=? AND owner_user_id=?",
            (run_id, owner),
        ).fetchone()
        artifacts = db.execute(
            """
            SELECT name, relative_path, media_type, created_at
            FROM artifacts WHERE run_id=? AND owner_user_id=?
            ORDER BY created_at
            """,
            (run_id, owner),
        ).fetchall()
    if not run:
        raise HTTPException(404, "Run not found")

    result = _public_run(run)
    log_path_value = str(run["log_path"] or "")
    log_path = Path(log_path_value) if log_path_value else None
    result["logs"] = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path and log_path.exists()
        else ""
    )
    result["artifacts"] = [
        {
            "name": artifact["name"],
            "media_type": artifact["media_type"],
            "created_at": artifact["created_at"],
            "url": f"/artifacts/{run_id}/{artifact['relative_path']}",
        }
        for artifact in artifacts
    ]
    return result


@app.get("/artifacts/{run_id}/{artifact_path:path}")
async def download_artifact(
    run_id: str,
    artifact_path: str,
    user: sqlite3.Row = Depends(require_user),
) -> FileResponse:
    owner = _owner_id(user)
    normalized = PurePosixPath(artifact_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise HTTPException(404, "Artifact not found")
    relative_path = normalized.as_posix()
    with connect() as db:
        artifact = db.execute(
            """
            SELECT relative_path, media_type FROM artifacts
            WHERE run_id=? AND owner_user_id=? AND relative_path=?
            """,
            (run_id, owner, relative_path),
        ).fetchone()
    if not artifact:
        raise HTTPException(404, "Artifact not found")

    run_root = resolve_within(ARTIFACTS_DIR, str(owner), run_id)
    path = resolve_within(run_root, str(artifact["relative_path"]))
    if not path.is_file():
        raise HTTPException(404, "Artifact not found")
    return FileResponse(path, media_type=str(artifact["media_type"]))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ready", "execution": "isolated-worker-only"}
