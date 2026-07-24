from __future__ import annotations

import json
import re
from typing import Any

from .autonomous_brain import GitHubAutonomousBrain
from .bot import AmosclaudBot, WRITE_ASSOCIATIONS, parse_command
from .codex_capabilities import prepare_codex_capabilities

PLAN_MARKER = "amosclaud-autonomous-plan"
CONTINUE_PHRASES = {
    "continue",
    "resume",
    "continue the task",
    "resume the task",
    "finish the remaining work",
    "finish remaining work",
    "complete the remaining work",
}


def _normalized_request(text: str) -> str:
    normalized = " ".join((text or "").strip().split()).lower()
    for name in ("@amosclaud-bot", "@amosclaud"):
        if normalized.startswith(name):
            return normalized[len(name) :].strip().rstrip(".")
    return normalized.rstrip(".")


def is_continue_request(text: str) -> bool:
    return _normalized_request(text) in CONTINUE_PHRASES


def plan_steps(command: str) -> tuple[str, ...]:
    if command == "fix":
        return (
            "Analyze the repository and the requested objective",
            "Retrieve relevant verified memory and approved lessons",
            "Select the bounded Codex engineering skill and permitted tools",
            "Design the smallest safe implementation",
            "Create or modify only approved files",
            "Add or update regression tests",
            "Run compilation, targeted tests, and diff review",
            "Commit verified changes and open a pull request",
        )
    if command == "verify":
        return (
            "Identify the relevant verification scope",
            "Retrieve prior evidence without treating it as current proof",
            "Select read and verification tools from the Codex contract",
            "Run repository checks and targeted tests",
            "Collect factual evidence",
            "Report the verified result",
        )
    if command == "review":
        return (
            "Inspect the proposed changes",
            "Retrieve relevant approved lessons and known failure patterns",
            "Select bounded repository and verification tools",
            "Identify correctness, security, and regression risks",
            "Check available verification evidence",
            "Report actionable findings",
        )
    return (
        "Inspect the repository",
        "Understand the objective and constraints",
        "Retrieve relevant verified memory and approved lessons",
        "Select the appropriate Autonomous Codex skill and read-only tools",
        "Identify the files and checks involved",
        "Report a recommended implementation path",
    )


def encode_plan_marker(command: str, objective: str) -> str:
    payload = json.dumps(
        {"version": 3, "command": command, "objective": objective},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"<!-- {PLAN_MARKER}:{payload} -->"


def decode_plan_marker(body: str) -> dict[str, str] | None:
    match = re.search(rf"<!--\s*{re.escape(PLAN_MARKER)}:(\{{.*?\}})\s*-->", body or "", re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    command = str(payload.get("command") or "").strip()
    objective = " ".join(str(payload.get("objective") or "").strip().split())
    if command not in {"fix", "inspect", "review", "verify"} or not objective:
        return None
    return {"command": command, "objective": objective}


def latest_plan(comments: list[dict[str, Any]]) -> dict[str, str] | None:
    for comment in reversed(comments):
        plan = decode_plan_marker(str(comment.get("body") or ""))
        if plan:
            return plan
    return None


def _brain_summary(context: dict[str, Any]) -> str:
    roles = ", ".join(item["role"] for item in context.get("agent_roles", [])) or "default roles"
    proven = context.get("proven_memories", [])
    failures = context.get("failed_attempts_to_avoid", [])
    lessons = context.get("approved_lessons", [])
    curriculum = context.get("current_curriculum", {})
    lines = [
        "## Autonomous brain context",
        "- **Runtime:** GitHub Actions repository-local brain",
        f"- **Agent roles:** {roles}",
        f"- **Curriculum:** Level {context.get('current_level', 1)} — {curriculum.get('track', 'ai-assistant')}",
        f"- **Relevant proven memories:** {len(proven)}",
        f"- **Known failed attempts to avoid:** {len(failures)}",
        f"- **Approved Academy lessons:** {len(lessons)}",
    ]
    if proven:
        lines.append("- **Strongest proven guidance:** " + str(proven[0].get("title") or "verified memory"))
    if failures:
        lines.append("- **Primary warning:** " + str(failures[0].get("title") or "previous failed attempt"))
    if lessons:
        lines.append("- **Most relevant lesson:** " + str(lessons[0].get("title") or "approved lesson"))
    lines.append("- **Truth rule:** Prior knowledge guides the task but never replaces current verification or grants write authority.")
    return "\n".join(lines)


def _codex_summary(context: dict[str, Any]) -> str:
    skill = context["skill"]
    limits = context["limits"]
    verification = context["verification"]
    tool_names = ", ".join(item["name"] for item in context["tools"]) or "none"
    approval_tools = ", ".join(context["approval_tools"]) or "none"
    return "\n".join(
        [
            "## Autonomous Codex capability context",
            f"- **Selected skill:** {skill['title']} (`{skill['name']}`)",
            f"- **Skill phases:** {' → '.join(skill['phases'])}",
            f"- **Permitted tools for this plan:** {tool_names}",
            f"- **Tools still requiring approval:** {approval_tools}",
            f"- **Execution limits:** {limits['max_iterations']} iterations, {limits['max_tool_calls']} tool calls, {limits['max_changed_files']} changed files",
            f"- **Required checks:** {', '.join(verification['required_checks'])}",
            "- **Workspace:** confined; parent traversal and secret files are forbidden",
            "- **External model execution:** disabled in Bot planning unless a separately configured runtime is explicitly invoked",
            f"- **Authority rule:** {context['authority_note']}",
        ]
    )


def format_plan(
    command: str,
    objective: str,
    *,
    resumed: bool = False,
    brain_context: dict[str, Any] | None = None,
    codex_context: dict[str, Any] | None = None,
) -> str:
    heading = "### Amosclaud — Autonomous Plan Resumed" if resumed else "### Amosclaud — Autonomous Plan"
    rendered = [f"{'🟩' if index < 2 else '⬜'} {step}" for index, step in enumerate(plan_steps(command))]
    brain = f"\n\n{_brain_summary(brain_context)}" if brain_context else ""
    codex = f"\n\n{_codex_summary(codex_context)}" if codex_context else ""
    return (
        f"{heading}\n\n"
        f"**Objective:** {objective}\n\n"
        + "\n".join(rendered)
        + brain
        + codex
        + "\n\nProceeding through the existing approval and publication gates. "
        + "The enforced order remains privacy, approval, verification, rollback, commit, and pull-request.\n"
        + encode_plan_marker(command, objective)
    )


def resolve_continuation(bot: AmosclaudBot, payload: dict[str, Any]) -> bool:
    comment = payload.get("comment") or {}
    if not is_continue_request(str(comment.get("body") or "")):
        return False
    issue = payload.get("issue") or {}
    number = int(issue.get("number"))
    comments = bot._request("GET", f"/repos/{bot.repository}/issues/{number}/comments?per_page=100")
    plan = latest_plan(comments if isinstance(comments, list) else [])
    if not plan:
        bot.post_comment(number, "### Amosclaud — Nothing to resume\nNo earlier autonomous plan was found in this issue. Start a task with `@amosclaud <objective>`.")
        return True
    comment["body"] = f"@amosclaud {plan['command']} {plan['objective']}"
    payload["comment"] = comment
    payload["_amosclaud_resumed_plan"] = plan
    return False


def announce_plan(bot: AmosclaudBot, payload: dict[str, Any]) -> None:
    comment = payload.get("comment") or {}
    association = str(comment.get("author_association") or "NONE").upper()
    command, objective = parse_command(str(comment.get("body") or ""))
    if command not in {"fix", "inspect", "review", "verify"} or not objective:
        return
    if command == "fix" and association not in WRITE_ASSOCIATIONS:
        return
    issue = payload.get("issue") or {}
    number = int(issue.get("number"))
    resumed = bool(payload.get("_amosclaud_resumed_plan"))
    brain = GitHubAutonomousBrain(bot.workspace, bot.repository)
    brain_context = brain.prepare(command, objective)
    codex_context = prepare_codex_capabilities(command, objective)
    bot.post_comment(
        number,
        format_plan(
            command,
            objective,
            resumed=resumed,
            brain_context=brain_context,
            codex_context=codex_context,
        ),
    )
