from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("AMOSCLAUD_DASHBOARD_DATA", BASE_DIR / "data"))
PROJECTS_DIR = DATA_DIR / "projects"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
DB_PATH = DATA_DIR / "dashboard.db"

for directory in (DATA_DIR, PROJECTS_DIR, ARTIFACTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def _fernet() -> Fernet:
    configured = os.getenv("AMOSCLAUD_DASHBOARD_KEY", "").strip()
    if configured:
        try:
            return Fernet(configured.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "AMOSCLAUD_DASHBOARD_KEY must be a valid Fernet key."
            ) from exc

    key_path = DATA_DIR / ".dashboard.key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes().strip())


FERNET = _fernet()
app = FastAPI(title="Amosclaud Workflow Dashboard", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
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
                run_id TEXT NOT NULL,
                name TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
                created_at INTEGER NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            """
        )


init_db()


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    repository_url: str = ""
    root_path: str = "."
    build_command: str = ""
    start_command: str = ""
    output_path: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    repository_url: str | None = None
    root_path: str | None = None
    build_command: str | None = None
    start_command: str | None = None
    output_path: str | None = None


class VariableInput(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: str
    is_secret: bool = True


class DomainInput(BaseModel):
    domain: str


class RunInput(BaseModel):
    objective: str = "Run agent workflow"


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
        "domain_token": row["domain_token"],
        "domain_verified": bool(row["domain_verified"]),
        "created_at": row["created_at"],
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / "dashboard.html")


@app.get("/api/projects")
async def list_projects() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
    return [project_dict(row) for row in rows]


@app.post("/api/projects", status_code=201)
async def create_project(payload: ProjectCreate) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    now = int(time.time())
    with connect() as db:
        db.execute(
            """
            INSERT INTO projects(
                id, name, repository_url, root_path, build_command,
                start_command, output_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                payload.name,
                payload.repository_url,
                payload.root_path,
                payload.build_command,
                payload.start_command,
                payload.output_path,
                now,
            ),
        )
    (PROJECTS_DIR / project_id).mkdir(parents=True, exist_ok=True)
    return await get_project(project_id)


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        variables = db.execute(
            """
            SELECT id, name, is_secret, created_at
            FROM variables WHERE project_id = ? ORDER BY name
            """,
            (project_id,),
        ).fetchall()
        runs = db.execute(
            """
            SELECT * FROM runs WHERE project_id = ?
            ORDER BY started_at DESC LIMIT 20
            """,
            (project_id,),
        ).fetchall()

    result = project_dict(row)
    result["variables"] = [
        {
            "id": variable["id"],
            "name": variable["name"],
            "is_secret": bool(variable["is_secret"]),
            "value": "••••••••" if variable["is_secret"] else "(stored)",
            "created_at": variable["created_at"],
        }
        for variable in variables
    ]
    result["runs"] = [dict(run) for run in runs]
    return result


@app.patch("/api/projects/{project_id}")
async def update_project(
    project_id: str, payload: ProjectUpdate
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return await get_project(project_id)

    allowed = {
        "name", "repository_url", "root_path", "build_command",
        "start_command", "output_path"
    }
    updates = {key: value for key, value in updates.items() if key in allowed}
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [project_id]

    with connect() as db:
        cursor = db.execute(
            f"UPDATE projects SET {assignments} WHERE id = ?", values
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Project not found")

    return await get_project(project_id)


@app.put("/api/projects/{project_id}/variables/{name}")
async def set_variable(
    project_id: str, name: str, payload: VariableInput
) -> dict[str, str]:
    if name != payload.name:
        raise HTTPException(400, "Variable name mismatch")

    encrypted = FERNET.encrypt(payload.value.encode())
    with connect() as db:
        exists = db.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(404, "Project not found")
        db.execute(
            """
            INSERT INTO variables(
                id, project_id, name, encrypted_value, is_secret, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, name) DO UPDATE SET
                encrypted_value = excluded.encrypted_value,
                is_secret = excluded.is_secret,
                created_at = excluded.created_at
            """,
            (
                str(uuid.uuid4()),
                project_id,
                payload.name,
                encrypted,
                int(payload.is_secret),
                int(time.time()),
            ),
        )
    return {"status": "saved", "name": name}


@app.delete("/api/projects/{project_id}/variables/{name}", status_code=204)
async def delete_variable(project_id: str, name: str) -> None:
    with connect() as db:
        db.execute(
            "DELETE FROM variables WHERE project_id = ? AND name = ?",
            (project_id, name),
        )


@app.post("/api/projects/{project_id}/domain")
async def set_domain(
    project_id: str, payload: DomainInput
) -> dict[str, Any]:
    domain = payload.domain.strip().lower()
    if not domain or "/" in domain or " " in domain:
        raise HTTPException(400, "Enter a valid hostname")

    token = "amosclaud-verification=" + secrets.token_urlsafe(24)
    with connect() as db:
        cursor = db.execute(
            """
            UPDATE projects
            SET domain = ?, domain_token = ?, domain_verified = 0
            WHERE id = ?
            """,
            (domain, token, project_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(404, "Project not found")

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
async def verify_domain(project_id: str) -> dict[str, Any]:
    """
    Production integration point.

    A real deployment should query DNS TXT records with dnspython and confirm
    that _amosclaud.<domain> contains the stored verification token. This
    starter intentionally does not mark a domain verified without a DNS check.
    """
    with connect() as db:
        row = db.execute(
            "SELECT domain, domain_token FROM projects WHERE id = ?",
            (project_id,),
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
        values = {
            b"".join(answer.strings).decode()
            for answer in answers
        }
    except Exception:
        return {
            "verified": False,
            "message": "DNS verification is not ready. Please try again later.",
        }

    verified = row["domain_token"] in values
    if verified:
        with connect() as db:
            db.execute(
                "UPDATE projects SET domain_verified = 1 WHERE id = ?",
                (project_id,),
            )
    return {
        "verified": verified,
        "message": (
            "Domain ownership verified."
            if verified
            else "TXT record was not found or does not match."
        ),
    }


def load_environment(project_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with connect() as db:
        rows = db.execute(
            "SELECT name, encrypted_value FROM variables WHERE project_id = ?",
            (project_id,),
        ).fetchall()
    for row in rows:
        try:
            result[row["name"]] = FERNET.decrypt(
                row["encrypted_value"]
            ).decode()
        except InvalidToken:
            raise RuntimeError(f"Could not decrypt variable {row['name']}")
    return result


def resolve_within(base: Path, *parts: str) -> Path:
    candidate = (base.joinpath(*parts)).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise HTTPException(400, "Path escapes allowed directory") from exc
    return candidate


@app.post("/api/projects/{project_id}/runs", status_code=202)
async def start_run(project_id: str, payload: RunInput) -> dict[str, Any]:
    """
    Starter synchronous executor.

    For production, submit this work to Amosclaud Task Router, Celery, RQ,
    Dramatiq, or a server-station runner instead of executing inside the API
    process.
    """
    try:
        uuid.UUID(project_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid project id") from exc

    with connect() as db:
        project = db.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise HTTPException(400, "Invalid project id")

    run_id = str(uuid.uuid4())
    run_dir = ARTIFACTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    started_at = int(time.time())

    with connect() as db:
        db.execute(
            """
            INSERT INTO runs(
                id, project_id, status, objective, started_at, log_path
            ) VALUES (?, ?, 'running', ?, ?, ?)
            """,
            (run_id, project_id, payload.objective, started_at, str(log_path)),
        )

    project_root = resolve_within(PROJECTS_DIR, project_id)
    workspace = resolve_within(project_root, project["root_path"])
    workspace.mkdir(parents=True, exist_ok=True)

    commands = [
        command for command in
        (project["build_command"], project["start_command"])
        if command.strip()
    ]
    if not commands:
        commands = ["python -c \"print('No command configured')\""]

    env = os.environ.copy()
    env.update(load_environment(project_id))
    status = "succeeded"
    exit_code = 0

    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"Objective: {payload.objective}\n")
        log.write(f"Workspace: {workspace}\n\n")
        for command in commands:
            log.write(f"$ {command}\n")
            log.flush()
            process = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                shell=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
            )
            exit_code = process.returncode
            if exit_code != 0:
                status = "failed"
                break

    output_path = project["output_path"].strip()
    if output_path:
        try:
            output = resolve_within(workspace, output_path)
        except HTTPException:
            status = "failed"
            with log_path.open("a", encoding="utf-8") as log:
                log.write("\nOutput path escapes workspace.\n")
            output = None
        if output is not None and output.exists():
            manifest = run_dir / "artifact-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "source": str(output),
                        "name": output.name,
                        "sha256": (
                            hashlib.sha256(output.read_bytes()).hexdigest()
                            if output.is_file()
                            else None
                        ),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    with connect() as db:
        db.execute(
            """
            UPDATE runs
            SET status = ?, finished_at = ?, exit_code = ?
            WHERE id = ?
            """,
            (status, int(time.time()), exit_code, run_id),
        )

    return await get_run(run_id)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(400, "Invalid run id")

    with connect() as db:
        run = db.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
    if not run:
        raise HTTPException(404, "Run not found")

    result = dict(run)
    log_path = Path(result["log_path"])
    result["logs"] = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.exists()
        else ""
    )
    result["log_url"] = f"/artifacts/{run_id}/run.log"
    artifacts_root = ARTIFACTS_DIR.resolve()
    manifest = (ARTIFACTS_DIR / run_id / "artifact-manifest.json").resolve()
    if artifacts_root not in manifest.parents:
        raise HTTPException(400, "Invalid run id")
    result["artifact_manifest_url"] = (
        f"/artifacts/{run_id}/artifact-manifest.json"
        if manifest.exists()
        else ""
    )
    return result


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ready",
        "database": str(DB_PATH),
        "projects_directory": str(PROJECTS_DIR),
        "artifacts_directory": str(ARTIFACTS_DIR),
    }
