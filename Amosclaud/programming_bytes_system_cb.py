"""Executable runtime for the literal Amosclaud programming-bytes CB chain."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from Amosclaud.byte.core import ByteFrame

CB_SEGMENTS = (
    "server.cb",
    "api.cb",
    "rest.cb",
    "next.cb",
    "cmood.cb",
    "remote.cb",
    "meta-package.cb",
    "autonomous.cb",
    "command.cb",
    "bumps.cb",
    "byte.cb",
    "pages.cb",
    "router.cb",
    "graphics.cb",
    "agent.cb",
    "word.cb",
    "global.cb",
    ".com.cb",
    "path.cb",
    "engine.cb",
    "github.cb",
    "yml.cb",
    "ci.cb",
    "meter.cb",
    "matrix.cb",
    "3d.cb",
    "localhost.cb",
    "programming.bytes.system.cb",
)
LITERAL_RELATIVE_PATH = Path("Amosclaud").joinpath(*CB_SEGMENTS)
_ROUTE = re.compile(r"^[a-z0-9][a-z0-9._/-]{1,199}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_ALLOWED_COMMANDS = {"build", "inspect", "route", "test", "verify"}


class ProgrammingBytesSystemError(ValueError):
    """Raised when a CB stage rejects an unsafe or invalid request."""


@dataclass(slots=True)
class ProgrammingBytesRequestCB:
    route: str
    payload: bytes
    method: str = "POST"
    command: str = "route"
    mode: str = "controlled"
    page: str = "/"
    host: str = "localhost"
    repository: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not _ROUTE.fullmatch(self.route):
            raise ProgrammingBytesSystemError("invalid CB route")
        if not isinstance(self.payload, bytes):
            raise ProgrammingBytesSystemError("CB payload must be bytes")
        if len(self.payload) > 64 * 1024 * 1024:
            raise ProgrammingBytesSystemError("CB payload exceeds 64 MiB")
        if self.method.upper() not in _ALLOWED_METHODS:
            raise ProgrammingBytesSystemError("unsupported REST method")
        if self.command.lower() not in _ALLOWED_COMMANDS:
            raise ProgrammingBytesSystemError("command is not allowlisted")
        if self.repository and not _REPOSITORY.fullmatch(self.repository):
            raise ProgrammingBytesSystemError("invalid GitHub repository name")
        path = PurePosixPath(self.page)
        if ".." in path.parts:
            raise ProgrammingBytesSystemError("page path traversal is not allowed")


@dataclass(frozen=True, slots=True)
class CBStageEvidence:
    index: int
    stage: str
    status: str
    elapsed_us: int
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProgrammingBytesResultCB:
    request_id: str
    status: str
    route: str
    output: ByteFrame
    stages: tuple[CBStageEvidence, ...]
    meter: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "route": self.route,
            "output": {
                "frame_id": self.output.frame_id,
                "route": self.output.route,
                "sha256": self.output.sha256,
                "payload_bytes": len(self.output.payload),
                "json": self.output.json(),
            },
            "stages": [
                {
                    "index": item.index,
                    "stage": item.stage,
                    "status": item.status,
                    "elapsed_us": item.elapsed_us,
                    "evidence": item.evidence,
                }
                for item in self.stages
            ],
            "meter": self.meter,
        }


StageHandler = Callable[[ProgrammingBytesRequestCB, dict[str, Any]], dict[str, Any]]


class ProgrammingBytesSystemCB:
    """Runs every literal CB segment as a measurable processing stage."""

    def __init__(self) -> None:
        self._handlers: dict[str, StageHandler] = {
            "server.cb": self._server,
            "api.cb": self._api,
            "rest.cb": self._rest,
            "cmood.cb": self._cmood,
            "remote.cb": self._remote,
            "meta-package.cb": self._meta_package,
            "autonomous.cb": self._autonomous,
            "command.cb": self._command,
            "bumps.cb": self._bumps,
            "byte.cb": self._byte,
            "pages.cb": self._pages,
            "router.cb": self._router,
            "graphics.cb": self._graphics,
            "agent.cb": self._agent,
            "word.cb": self._word,
            "global.cb": self._global,
            ".com.cb": self._dot_com,
            "path.cb": self._path,
            "engine.cb": self._engine,
            "github.cb": self._github,
            "yml.cb": self._yml,
            "ci.cb": self._ci,
            "meter.cb": self._meter,
            "matrix.cb": self._matrix,
            "3d.cb": self._three_d,
            "localhost.cb": self._localhost,
            "programming.bytes.system.cb": self._complete,
        }

    @staticmethod
    def literal_path(repository_root: Path | None = None) -> Path:
        base = Path(repository_root).resolve() if repository_root else Path(__file__).parent.parent
        return base / LITERAL_RELATIVE_PATH

    def verify_layout(self, repository_root: Path | None = None) -> dict[str, Any]:
        target = self.literal_path(repository_root)
        manifest = target / "manifest.json"
        if not target.is_dir() or not manifest.is_file():
            raise ProgrammingBytesSystemError("literal CB path or manifest is missing")
        document = json.loads(manifest.read_text(encoding="utf-8"))
        if tuple(document.get("segments", [])) != CB_SEGMENTS:
            raise ProgrammingBytesSystemError("literal CB manifest segment order is invalid")
        return {
            "valid": True,
            "path": str(target),
            "segments": len(CB_SEGMENTS),
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        }

    def execute(self, request: ProgrammingBytesRequestCB) -> ProgrammingBytesResultCB:
        request.validate()
        request_id = uuid.uuid4().hex
        state: dict[str, Any] = {"request_id": request_id, "trace": []}
        evidence = []
        for index, stage in enumerate(CB_SEGMENTS, start=1):
            started = time.perf_counter_ns()
            handler = self._handlers.get(stage, self._next)
            detail = handler(request, state)
            elapsed = max(1, (time.perf_counter_ns() - started) // 1000)
            state["trace"].append(stage)
            evidence.append(CBStageEvidence(index, stage, "passed", elapsed, detail))
        payload = {
            "status": "completed",
            "request_id": request_id,
            "route": request.route,
            "payload_sha256": hashlib.sha256(request.payload).hexdigest(),
            "trace": state["trace"],
            "context": {key: value for key, value in state.items() if key != "trace"},
        }
        output = ByteFrame.from_json(f"{request.route}.result", payload)
        return ProgrammingBytesResultCB(
            request_id=request_id,
            status="completed",
            route=request.route,
            output=output,
            stages=tuple(evidence),
            meter={
                "input_bytes": len(request.payload),
                "output_bytes": len(output.payload),
                "stages": len(evidence),
                "elapsed_us": sum(item.elapsed_us for item in evidence),
            },
        )

    @staticmethod
    def _server(_request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["server"] = "amosclaud-programming-bytes"
        return {"service": state["server"]}

    @staticmethod
    def _api(_request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["api_version"] = "v1"
        return {"version": "v1"}

    @staticmethod
    def _rest(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["method"] = request.method.upper()
        return {"method": state["method"]}

    @staticmethod
    def _next(_request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        return {"sequence": len(state["trace"]) + 1}

    @staticmethod
    def _cmood(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["mode"] = request.mode
        return {"mode": request.mode}

    @staticmethod
    def _remote(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        remote = str(request.metadata.get("remote", "local-only"))
        state["remote"] = remote
        return {"target": remote, "network_called": False}

    @staticmethod
    def _meta_package(_request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["package"] = "Amosclaud"
        return {"package": "Amosclaud", "format": "cb"}

    @staticmethod
    def _autonomous(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        authorized = bool(request.metadata.get("autonomous_authorized", False))
        state["autonomous_authorized"] = authorized
        return {"authorized": authorized, "executed_external_action": False}

    @staticmethod
    def _command(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["command"] = request.command.lower()
        return {"command": state["command"], "shell_executed": False}

    @staticmethod
    def _bumps(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        version = str(request.metadata.get("version", "1.0.0"))
        state["version"] = version
        return {"version": version}

    @staticmethod
    def _byte(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        digest = hashlib.sha256(request.payload).hexdigest()
        state["input_sha256"] = digest
        return {"bytes": len(request.payload), "sha256": digest}

    @staticmethod
    def _pages(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["page"] = request.page
        return {"page": request.page}

    @staticmethod
    def _router(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["route"] = request.route
        return {"matched": True, "route": request.route}

    @staticmethod
    def _graphics(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        graphics = str(request.metadata.get("graphics", "none"))
        state["graphics"] = graphics
        return {"renderer": graphics}

    @staticmethod
    def _agent(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        agent = str(request.metadata.get("agent", "Amosclaud Autonomous"))
        state["agent"] = agent
        return {"agent": agent}

    @staticmethod
    def _word(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        words = len(request.payload.decode("utf-8", errors="ignore").split())
        state["words"] = words
        return {"words": words}

    @staticmethod
    def _global(_request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["scope"] = "request-isolated"
        return {"scope": state["scope"]}

    @staticmethod
    def _dot_com(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["domain"] = request.host
        return {"domain": request.host}

    @staticmethod
    def _path(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["normalized_path"] = PurePosixPath(request.page).as_posix()
        return {"path": state["normalized_path"]}

    @staticmethod
    def _engine(_request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["engine"] = "programming-bytes-system-cb"
        return {"engine": state["engine"]}

    @staticmethod
    def _github(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["repository"] = request.repository
        return {"repository": request.repository, "network_called": False}

    @staticmethod
    def _yml(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        workflow = request.metadata.get("workflow", {})
        state["workflow"] = workflow if isinstance(workflow, dict) else {}
        return {"keys": sorted(state["workflow"])}

    @staticmethod
    def _ci(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        checks = request.metadata.get("checks", ["integrity", "route"])
        state["checks"] = list(checks) if isinstance(checks, (list, tuple)) else []
        return {"checks": state["checks"], "status": "configured"}

    @staticmethod
    def _meter(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["meter_input_bytes"] = len(request.payload)
        return {"input_bytes": len(request.payload)}

    @staticmethod
    def _matrix(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        width = max(1, int(request.metadata.get("matrix_width", 1)))
        height = max(1, int(request.metadata.get("matrix_height", 1)))
        state["matrix"] = {"width": width, "height": height}
        return state["matrix"]

    @staticmethod
    def _three_d(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        enabled = bool(request.metadata.get("3d", False))
        state["3d"] = {"enabled": enabled, "objects": int(enabled)}
        return state["3d"]

    @staticmethod
    def _localhost(request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        local = request.host in {"localhost", "127.0.0.1", "::1"}
        state["localhost"] = local
        return {"local": local}

    @staticmethod
    def _complete(_request: ProgrammingBytesRequestCB, state: dict[str, Any]) -> dict[str, Any]:
        state["complete"] = True
        return {"complete": True, "prior_stages": len(state["trace"])}
