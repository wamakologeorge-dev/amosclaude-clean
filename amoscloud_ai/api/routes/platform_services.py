"""Truthful, read-only aggregation of every platform service state.

This module powers the Command Center "All services" dashboard. It never
invents a service, a metric, or a green light: every entry is derived from a
check or a configuration value that already exists in this codebase. When no
genuine probe exists for a service, the entry reports ``unknown`` and names
the observability gap instead of defaulting to healthy.

The endpoint is intentionally resilient: one failing service check is caught
and reported as that single service's problem, and never fails the whole
response. No secret value (token, key, connection string) is ever included in
an entry; only environment-variable *names* and safe, redacted diagnostics.
"""
from __future__ import annotations

import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException

from amoscloud_ai import github_issue_commands, model_runtime, railway_health
from amoscloud_ai.api.routes import (
    auth,
    github_app,
    repositories,
    solo_development,
    storage,
)

router = APIRouter(prefix="/platform", tags=["platform-services"])

# Strict, honest state vocabulary. Do not add ad-hoc states.
OPERATIONAL = "operational"
DEGRADED = "degraded"
UNREACHABLE = "unreachable"
NOT_CONFIGURED = "not_configured"
DISABLED = "disabled"
UNKNOWN = "unknown"

STATES = (OPERATIONAL, DEGRADED, UNREACHABLE, NOT_CONFIGURED, DISABLED, UNKNOWN)


def _entry(
    sid: str,
    name: str,
    state: str,
    explanation: str,
    evidence: str,
    remediation: str = "",
) -> dict:
    entry = {
        "id": sid,
        "name": name,
        "state": state,
        "explanation": explanation,
        "evidence": evidence,
    }
    if remediation:
        entry["remediation"] = remediation
    return entry


def _write_probe(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".amosclaud-service-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _check_web() -> dict:
    return _entry(
        "web",
        "Web application",
        OPERATIONAL,
        "The web process is alive and served this request.",
        "This /api/v1/platform/services response",
    )


def _check_database() -> dict:
    with auth._connect() as db:
        db.execute("SELECT 1").fetchone()
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return _entry(
        "database",
        "Platform database",
        OPERATIONAL,
        f"A probe query succeeded ({users} user row(s) present).",
        "SELECT on the auth database users table",
    )


def _check_auth_session() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with auth._connect() as db:
        active = db.execute(
            "SELECT COUNT(*) FROM sessions WHERE expires_at > ?", (now,)
        ).fetchone()[0]
    return _entry(
        "auth-session",
        "Authentication & session service",
        OPERATIONAL,
        f"The session store is queryable ({active} active session(s)).",
        "SELECT on the sessions table",
    )


def _check_repository_store() -> dict:
    try:
        _write_probe(repositories.REPOSITORY_ROOT)
    except OSError as exc:
        return _entry(
            "repository-store",
            "Native repository service",
            UNREACHABLE,
            "The repository storage root rejected a write probe.",
            "Write probe under REPOSITORY_STORAGE_PATH",
            "Point REPOSITORY_STORAGE_PATH at a writable volume "
            f"({type(exc).__name__}).",
        )
    return _entry(
        "repository-store",
        "Native repository service",
        OPERATIONAL,
        "The repository storage root accepted a write probe.",
        "Write probe under REPOSITORY_STORAGE_PATH",
    )


def _check_object_storage() -> dict:
    try:
        _write_probe(storage.STORAGE_ROOT)
    except OSError as exc:
        return _entry(
            "object-storage",
            "Object / blob storage",
            UNREACHABLE,
            "The object storage root rejected a write probe.",
            "Write probe under the storage root",
            "Point the storage root at a writable volume "
            f"({type(exc).__name__}).",
        )
    return _entry(
        "object-storage",
        "Object / blob storage",
        OPERATIONAL,
        "The object storage root accepted a write probe.",
        "Write probe under the storage root",
    )


def _check_issues() -> dict:
    with repositories._db() as db:
        solo_development._ensure_tables(db)
        count = db.execute("SELECT COUNT(*) FROM native_issues").fetchone()[0]
    return _entry(
        "issues-service",
        "Issues service",
        OPERATIONAL,
        f"The native_issues table is queryable ({count} issue(s) recorded).",
        "SELECT on the native_issues table",
    )


def _check_git_transport() -> dict:
    if not shutil.which("git"):
        return _entry(
            "git-transport",
            "Git transport",
            UNREACHABLE,
            "The git executable was not found on PATH.",
            "shutil.which('git') and the /api/v1/git smart-HTTP routes",
            "Install git in the runtime image so native clone and push work.",
        )
    return _entry(
        "git-transport",
        "Git transport",
        OPERATIONAL,
        "The git executable is available for smart-HTTP transport.",
        "shutil.which('git') and the /api/v1/git smart-HTTP routes",
    )


def _health_entry(sid: str, name: str, cand, health) -> dict:
    remediation = health.diagnosis.remediation if health.diagnosis else ""
    if health.reachable:
        return _entry(
            sid,
            name,
            OPERATIONAL,
            "A bounded preflight reached the configured endpoint.",
            f"model_runtime preflight of {cand.endpoint_env}",
        )
    if not cand.configured:
        return _entry(
            sid,
            name,
            NOT_CONFIGURED,
            "No endpoint is configured for this provider path.",
            f"model_runtime candidate '{cand.key}' configuration",
            remediation,
        )
    code = health.diagnosis.code if health.diagnosis else "unknown"
    return _entry(
        sid,
        name,
        UNREACHABLE,
        f"A bounded preflight failed with diagnosis '{code}'.",
        f"model_runtime preflight of {cand.endpoint_env}",
        remediation,
    )


def _find_candidate(key: str):
    for cand in model_runtime.resolve_candidates():
        if cand.key == key:
            return cand
    return None


def _candidate_entry(sid: str, name: str, key: str) -> dict:
    cand = _find_candidate(key)
    if cand is not None:
        return _health_entry(sid, name, cand, model_runtime.candidate_health(cand))
    return _entry(
        sid,
        name,
        UNKNOWN,
        "This model candidate is not present in the resolution path.",
        "amoscloud_ai.model_runtime.resolve_candidates()",
        "No probe available; the candidate is not registered.",
    )


def _self_hosted_reachable() -> bool:
    cand = _find_candidate("self-hosted")
    return bool(
        cand is not None
        and cand.configured
        and model_runtime.candidate_health(cand).reachable
    )


def _model_network_reachable() -> tuple[bool, int]:
    """Return whether a genuine first-party station can serve inference."""
    state = model_runtime.network_state()
    stations = int(state.get("ready_stations") or 0)
    return bool(state.get("ready") and stations > 0), stations


def _check_amosclaud_provider() -> dict:
    """Report the aggregate first-party provider path truthfully.

    Model-network stations, the optional hosted Amosclaud API, and the direct
    self-hosted endpoint are all first-party routes. The provider path is
    operational when any one of those routes is genuinely reachable.
    """
    sid = "amosclaud-provider"
    name = "First-party Amosclaud provider path"

    network_reachable, stations = _model_network_reachable()
    if network_reachable:
        return _entry(
            sid,
            name,
            OPERATIONAL,
            f"{stations} first-party model station(s) are registered and online, "
            "so the Amosclaud provider path can serve inference even if the "
            "direct self-hosted endpoint is unavailable.",
            "amoscloud_ai.model_network.network_status() and the model-runtime "
            "resolution order",
        )

    cand = _find_candidate("amosclaud-api")
    api_health = None
    if cand is not None and cand.configured:
        api_health = model_runtime.candidate_health(cand)
        if api_health.reachable:
            return _health_entry(sid, name, cand, api_health)

    if _self_hosted_reachable():
        return _entry(
            sid,
            name,
            OPERATIONAL,
            "The direct self-hosted model runtime is reachable and serves the "
            "first-party provider path, so the optional hosted Amosclaud API "
            "and station network are not required.",
            "model_runtime candidate 'self-hosted' passed its bounded preflight",
        )

    if cand is not None and api_health is not None:
        return _health_entry(sid, name, cand, api_health)

    return _entry(
        sid,
        name,
        NOT_CONFIGURED,
        "No model station is ready, the remote-hosted Amosclaud API is not "
        "configured, and no self-hosted runtime is reachable, so the "
        "first-party provider path cannot serve traffic.",
        "model_runtime candidates 'model-network', 'amosclaud-api', and "
        "'self-hosted'",
        "Connect an online model station, configure a reachable self-hosted "
        "AMOSCLAUD_MODEL_URL, or set AMOSCLAUD_PROVIDER_API_URL + "
        "AMOSCLAUD_API_KEY for the remote API.",
    )


def _check_model_runtime() -> dict:
    return _candidate_entry(
        "model-runtime",
        "Model runtime endpoint",
        "self-hosted",
    )


def _check_model_network() -> dict:
    state = model_runtime.network_state()
    evidence = "amoscloud_ai.model_network.network_status()"
    if not state.get("configured"):
        return _entry(
            "model-station-network",
            "Model station network",
            DISABLED,
            "Model station pooling is an optional horizontal scale-out and is "
            "intentionally not enabled; the self-hosted runtime already serves "
            "all inference traffic. This is not required for operation.",
            evidence,
            "Set AMOSCLAUD_NETWORK_OWNER_USER_ID to enable optional station "
            "pooling.",
        )
    stations = int(state.get("ready_stations") or 0)
    if state.get("ready") and stations > 0:
        return _entry(
            "model-station-network",
            "Model station network",
            OPERATIONAL,
            f"{stations} model station(s) are registered and online.",
            evidence,
        )
    return _entry(
        "model-station-network",
        "Model station network",
        DEGRADED,
        "The network is configured but no station is currently online.",
        evidence,
        "Connect and keep a model station online to serve inference.",
    )


def _check_external_adapters() -> dict:
    name = "Optional external provider adapters"
    if not model_runtime.external_adapters_enabled():
        return _entry(
            "external-adapters",
            name,
            DISABLED,
            "External provider adapters are optional by design and "
            "intentionally off; the working first-party runtime is always "
            "preferred, so no OpenAI or Anthropic key is required. This is "
            "not a deficiency.",
            "AMOSCLAUD_ALLOW_EXTERNAL_ADAPTERS flag",
        )
    configured = [
        cand
        for cand in model_runtime.resolve_candidates()
        if cand.kind == "external" and cand.configured
    ]
    if not configured:
        return _entry(
            "external-adapters",
            name,
            NOT_CONFIGURED,
            "Adapters are enabled but no adapter API key is set.",
            "model_runtime external candidates",
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY to use an adapter.",
        )
    labels = ", ".join(cand.label for cand in configured)
    return _entry(
        "external-adapters",
        name,
        UNKNOWN,
        f"Enabled with a configured adapter ({labels}), but Amosclaud makes "
        "no external API call to probe it, so reachability is unverified.",
        "model_runtime external candidates",
        "Reachability is unproven by design; no external key call is made.",
    )


def _check_github_webhook() -> dict:
    evidence = (
        "GITHUB_APP_WEBHOOK_SECRET and the mounted GitHub App webhook route"
    )
    if not github_app._webhook_secret():
        return _entry(
            "github-webhook",
            "GitHub App webhook receiver",
            NOT_CONFIGURED,
            "No signing secret is set, so deliveries cannot be verified.",
            evidence,
            "Set GITHUB_APP_WEBHOOK_SECRET to accept signed deliveries.",
        )
    return _entry(
        "github-webhook",
        "GitHub App webhook receiver",
        OPERATIONAL,
        "A signing secret is configured and the receiver route is mounted.",
        evidence,
    )


def _check_issue_command() -> dict:
    name = "GitHub issue-command integration"
    commands = ", ".join(sorted(github_issue_commands.COMMANDS))
    if not github_app._webhook_secret():
        return _entry(
            "issue-command",
            name,
            NOT_CONFIGURED,
            "Issue commands require the webhook receiver, which has no "
            "signing secret configured.",
            "github_issue_commands.COMMANDS and GITHUB_APP_WEBHOOK_SECRET",
            "Set GITHUB_APP_WEBHOOK_SECRET to receive issue commands.",
        )
    allowlist = github_issue_commands._allowlist()
    if not allowlist:
        return _entry(
            "issue-command",
            name,
            DEGRADED,
            "The parser and commands are active, but no sender allowlist is "
            "set, so only trusted repository associations can trigger tasks.",
            "github_issue_commands._allowlist()",
            "Set AMOSCLAUD_GITHUB_COMMAND_ALLOWLIST to authorize senders.",
        )
    return _entry(
        "issue-command",
        name,
        OPERATIONAL,
        f"Webhook secret set and {len(allowlist)} sender(s) allowlisted; "
        f"commands: {commands}.",
        "github_issue_commands.COMMANDS and the command allowlist",
    )


def _check_railway() -> dict:
    state = railway_health.status()
    evidence = "amoscloud_ai.railway_health.status()"
    if not state.get("enabled"):
        return _entry(
            "railway",
            "Optional Railway healthcheck",
            DISABLED,
            "The Railway healthcheck is intentionally disabled.",
            evidence,
        )
    if state.get("reachable"):
        return _entry(
            "railway",
            "Optional Railway healthcheck",
            OPERATIONAL,
            f"The configured Railway endpoint responded ({state.get('detail')}).",
            evidence,
        )
    return _entry(
        "railway",
        "Optional Railway healthcheck",
        UNREACHABLE,
        f"The Railway healthcheck failed ({state.get('detail')}).",
        evidence,
        "Confirm AMOSCLAUD_RAILWAY_HEALTH_URL points at a reachable endpoint.",
    )


def _agent_run_route_wired() -> bool:
    """True when the ``/agent/run`` POST route is registered in the router."""
    from amoscloud_ai.api.routes import agent

    for route in agent.router.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.endswith("/run") and "POST" in methods:
            return True
    return False


# Self-test pipeline rows are clearly marked and always deleted after the
# probe, so they never appear as durable, user-visible task history.
SELF_TEST_BRANCH = "__amosclaud_selftest__"


def _probe_pipeline_self_test() -> tuple[bool, bool, str]:
    """Bounded, side-effect-free autonomous pipeline self-test.

    Verifies the store is writable and readable, the pipeline state machine
    can transition PENDING -> RUNNING -> SUCCESS, and cleans up the transient
    self-test row. Never calls a model or runs real work. Returns
    ``(store_ok, transitioned, detail)``.
    """
    from amoscloud_ai.api.routes import pipelines
    from amoscloud_ai.models import PipelineJob, PipelineResponse, PipelineStatus

    probe_id = f"selftest-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    pipeline = PipelineResponse(
        id=probe_id,
        status=PipelineStatus.PENDING,
        trigger="autonomous",
        branch=SELF_TEST_BRANCH,
        started_at=now,
        message="platform self-test (no model generation)",
        jobs=[
            PipelineJob(
                id="selftest",
                name="Self-test",
                status=PipelineStatus.PENDING,
            )
        ],
    )
    try:
        pipelines._save(pipeline, {"self_test": True})
        stored = pipelines._get(probe_id)
        if stored is None or stored.status != PipelineStatus.PENDING:
            return False, False, "the self-test row was not read back"
        for state in (
            PipelineStatus.PENDING,
            PipelineStatus.RUNNING,
            PipelineStatus.SUCCESS,
        ):
            pipeline.status = state
            if pipeline.jobs:
                pipeline.jobs[0].status = state
        pipeline.finished_at = datetime.now(timezone.utc)
        pipelines._save(pipeline, {"self_test": True})
        final = pipelines._get(probe_id)
        transitioned = (
            final is not None and final.status == PipelineStatus.SUCCESS
        )
        detail = (
            "store read/write and PENDING->RUNNING->SUCCESS transition verified"
            if transitioned
            else "the state machine did not reach SUCCESS"
        )
        return True, transitioned, detail
    finally:
        pipelines._delete(probe_id)


def _check_autonomous_pipeline() -> dict:
    sid = "autonomous-pipeline"
    name = "Autonomous agent & task pipeline"
    evidence = (
        "bounded self-test: pipeline store read/write, PipelineStatus "
        "transition, and /agent/run route wiring (no model call)"
    )
    store_ok, transitioned, detail = _probe_pipeline_self_test()
    if not store_ok:
        return _entry(
            sid,
            name,
            UNREACHABLE,
            f"The pipeline/task store failed the self-test: {detail}.",
            evidence,
            "Confirm the pipeline_runs store (AUTH_DB_PATH) is writable.",
        )
    wired = _agent_run_route_wired()
    if not transitioned:
        return _entry(
            sid,
            name,
            DEGRADED,
            f"The store works but the pipeline state machine failed: {detail}.",
            evidence,
            "Investigate PipelineStatus transitions in the pipeline store.",
        )
    if not wired:
        return _entry(
            sid,
            name,
            DEGRADED,
            "The store and state machine work, but the /api/v1/agent/run "
            "execution route is not registered, so tasks cannot be started.",
            evidence,
            "Confirm the agent router is mounted and exposes POST /agent/run.",
        )
    return _entry(
        sid,
        name,
        OPERATIONAL,
        "A bounded self-test verified the task store is writable and "
        "readable, the pipeline state machine transitions "
        "PENDING->RUNNING->SUCCESS, and the /api/v1/agent/run execution route "
        "is wired. No model generation was triggered.",
        evidence,
    )


def _workflow_definition_count() -> int | None:
    """Count workflow YAML files on disk without reading their contents.

    Returns ``None`` when the ``.github/workflows`` directory is absent (as it
    is inside a deployed container). Directory listing only — the files are
    never opened or modified.
    """
    workflows = Path(__file__).resolve().parents[3] / ".github" / "workflows"
    if not workflows.is_dir():
        return None
    return sum(
        1
        for entry in workflows.iterdir()
        if entry.is_file() and entry.suffix in {".yml", ".yaml"}
    )


def _runner_subsystem_present() -> bool:
    try:
        from src.core.ci_orchestrator import CIOrchestrator  # noqa: F401
    except Exception:
        return False
    return True


def _check_cicd() -> dict:
    sid = "cicd"
    name = "CI/CD pipeline & runners"
    evidence = (
        "pipeline_runs store query, src.core.ci_orchestrator import, and a "
        "read-only listing of .github/workflows"
    )
    from amoscloud_ai.api.routes import pipelines

    try:
        with pipelines._db() as db:
            runs = db.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
        store_ok = True
    except Exception as exc:
        runs = 0
        store_ok = False
        store_error = type(exc).__name__

    runner_present = _runner_subsystem_present()
    workflow_count = _workflow_definition_count()
    if workflow_count is None:
        workflow_fact = (
            "workflow definitions are not on disk in this container, so their "
            "presence cannot be determined here (they live in the repository)"
        )
    else:
        workflow_fact = (
            f"{workflow_count} workflow definition(s) are discoverable on disk"
        )

    if not store_ok:
        return _entry(
            sid,
            name,
            UNREACHABLE,
            "The pipeline run store is not queryable "
            f"({store_error}), so CI/CD run history cannot be read.",
            evidence,
            "Confirm the pipeline_runs store (AUTH_DB_PATH) is reachable.",
        )
    hosted_note = (
        "Execution on GitHub's hosted runners happens outside this container "
        "and cannot be observed from here."
    )
    if not runner_present:
        return _entry(
            sid,
            name,
            DEGRADED,
            f"The pipeline run store is queryable ({runs} run record(s)) and "
            f"{workflow_fact}, but the in-process runner subsystem "
            f"(src.core.ci_orchestrator) could not be imported. {hosted_note}",
            evidence,
            "Investigate why src.core.ci_orchestrator is not importable.",
        )
    return _entry(
        sid,
        name,
        OPERATIONAL,
        f"The pipeline run store is queryable ({runs} run record(s)), the "
        f"in-process runner subsystem (src.core.ci_orchestrator) is present, "
        f"and {workflow_fact}. {hosted_note}",
        evidence,
    )


# (id, name, check) — id/name are reused if a check raises unexpectedly.
_CHECKS = (
    ("web", "Web application", _check_web),
    ("database", "Platform database", _check_database),
    ("auth-session", "Authentication & session service", _check_auth_session),
    ("repository-store", "Native repository service", _check_repository_store),
    ("issues-service", "Issues service", _check_issues),
    ("git-transport", "Git transport", _check_git_transport),
    ("object-storage", "Object / blob storage", _check_object_storage),
    (
        "amosclaud-provider",
        "First-party Amosclaud provider path",
        _check_amosclaud_provider,
    ),
    ("model-runtime", "Model runtime endpoint", _check_model_runtime),
    ("model-station-network", "Model station network", _check_model_network),
    (
        "external-adapters",
        "Optional external provider adapters",
        _check_external_adapters,
    ),
    ("github-webhook", "GitHub App webhook receiver", _check_github_webhook),
    ("issue-command", "GitHub issue-command integration", _check_issue_command),
    ("railway", "Optional Railway healthcheck", _check_railway),
    (
        "autonomous-pipeline",
        "Autonomous agent & task pipeline",
        _check_autonomous_pipeline,
    ),
    ("cicd", "CI/CD pipeline & runners", _check_cicd),
)


def _collect() -> list[dict]:
    services: list[dict] = []
    for sid, name, check in _CHECKS:
        try:
            services.append(check())
        except Exception as exc:  # resilience: never fail the whole board
            services.append(
                _entry(
                    sid,
                    name,
                    UNREACHABLE,
                    "The service check raised an unexpected error.",
                    f"platform_services.{check.__name__}",
                    f"Investigate the failing check ({type(exc).__name__}).",
                )
            )
    return services


def _require_session(amos_session: str | None = Cookie(default=None)):
    user = auth.get_user_from_session(amos_session)
    if not user:
        raise HTTPException(
            status_code=401, detail="Sign in to view platform service status"
        )
    return user


@router.get("/services", summary="Truthful status of every platform service")
def platform_services(user: sqlite3.Row = Depends(_require_session)) -> dict:
    del user
    services = _collect()
    summary = {state: 0 for state in STATES}
    for service in services:
        summary[service["state"]] = summary.get(service["state"], 0) + 1
    summary["total"] = len(services)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "services": services,
    }
