"""Deterministic workflow health classification for Amosclaud.

A repository is verified only when every required check is present and has an
accepted conclusion. Conditional checks may be declared as expected skips for
a specific event. Missing, pending, cancelled, or unexpectedly skipped checks
remain visible and prevent a 100% claim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase

PASSING_CONCLUSIONS = {"success", "neutral"}
FAILING_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "stale",
    "timed_out",
}
PENDING_STATUSES = {"in_progress", "pending", "queued", "requested", "waiting"}


@dataclass(frozen=True)
class CheckState:
    name: str
    state: str
    conclusion: str | None
    required: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state,
            "conclusion": self.conclusion,
            "required": self.required,
            "detail": self.detail,
        }


def _matches(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(name, pattern) for pattern in patterns)


def _normalize_checks(checks: Iterable[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    normalized: dict[str, Mapping[str, object]] = {}
    for check in checks:
        name = str(check.get("name") or "").strip()
        if not name:
            continue
        normalized[name] = check
    return normalized


def evaluate_health(
    checks: Iterable[Mapping[str, object]],
    *,
    required: Sequence[str],
    expected_skips: Sequence[str] = (),
    optional: Sequence[str] = (),
) -> dict[str, object]:
    """Evaluate check-run data using an explicit event-aware contract."""

    by_name = _normalize_checks(checks)
    states: list[CheckState] = []

    for name in required:
        check = by_name.get(name)
        if check is None:
            states.append(
                CheckState(
                    name=name,
                    state="MISSING",
                    conclusion=None,
                    required=True,
                    detail="required check did not report a result",
                )
            )
            continue
        states.append(_classify(name, check, required=True, expected_skips=expected_skips))

    declared = set(required) | set(optional)
    for name in optional:
        check = by_name.get(name)
        if check is None:
            continue
        states.append(_classify(name, check, required=False, expected_skips=expected_skips))

    for name, check in sorted(by_name.items()):
        if name in declared:
            continue
        states.append(_classify(name, check, required=False, expected_skips=expected_skips))

    counts: dict[str, int] = {}
    for state in states:
        counts[state.state] = counts.get(state.state, 0) + 1

    blocking_states = {"FAILED", "MISSING", "UNEXPECTED_SKIP", "UNKNOWN"}
    has_blocker = any(state.required and state.state in blocking_states for state in states)
    has_pending = any(state.required and state.state == "PENDING" for state in states)
    all_required_verified = all(
        state.state in {"PASSED", "EXPECTED_SKIP"}
        for state in states
        if state.required
    ) and bool(required)

    if has_blocker:
        overall = "ACTION_NEEDED"
        exit_code = 1
    elif has_pending:
        overall = "PENDING"
        exit_code = 2
    elif all_required_verified:
        overall = "VERIFIED"
        exit_code = 0
    else:
        overall = "INCOMPLETE"
        exit_code = 1

    required_total = len(required)
    required_verified = sum(
        1
        for state in states
        if state.required and state.state in {"PASSED", "EXPECTED_SKIP"}
    )
    percentage = round((required_verified / required_total) * 100) if required_total else 0

    return {
        "schema": "amosclaud.health-contract.v1",
        "overall": overall,
        "percentage": percentage,
        "required_total": required_total,
        "required_verified": required_verified,
        "counts": counts,
        "checks": [state.as_dict() for state in states],
        "exit_code": exit_code,
        "truthful_100_percent": overall == "VERIFIED" and percentage == 100,
    }


def _classify(
    name: str,
    check: Mapping[str, object],
    *,
    required: bool,
    expected_skips: Sequence[str],
) -> CheckState:
    status = str(check.get("status") or "").strip().lower()
    raw_conclusion = check.get("conclusion")
    conclusion = str(raw_conclusion).strip().lower() if raw_conclusion is not None else None

    if status in PENDING_STATUSES or (status != "completed" and conclusion is None):
        return CheckState(name, "PENDING", conclusion, required, f"status={status or 'unknown'}")
    if conclusion in PASSING_CONCLUSIONS:
        return CheckState(name, "PASSED", conclusion, required, f"conclusion={conclusion}")
    if conclusion == "skipped":
        if _matches(name, expected_skips):
            return CheckState(
                name,
                "EXPECTED_SKIP",
                conclusion,
                required,
                "conditional check was allowed to skip for this event",
            )
        return CheckState(
            name,
            "UNEXPECTED_SKIP",
            conclusion,
            required,
            "skip was not declared by the event contract",
        )
    if conclusion in FAILING_CONCLUSIONS:
        return CheckState(name, "FAILED", conclusion, required, f"conclusion={conclusion}")
    return CheckState(
        name,
        "UNKNOWN",
        conclusion,
        required,
        f"status={status or 'unknown'}, conclusion={conclusion or 'none'}",
    )


def render_markdown(result: Mapping[str, object]) -> str:
    """Render a compact status report suitable for issues and pull requests."""

    overall = str(result.get("overall") or "UNKNOWN")
    percentage = int(result.get("percentage") or 0)
    symbol = {
        "VERIFIED": "🟩",
        "PENDING": "🟨",
        "ACTION_NEEDED": "🟥",
        "INCOMPLETE": "⬜",
    }.get(overall, "⬜")
    lines = [
        "### Amosclaud — Verified Health Contract",
        "",
        f"**Overall:** {symbol} {overall}",
        f"**Required verification:** {percentage}%",
        "",
    ]
    for check in result.get("checks", []):
        state = str(check.get("state") or "UNKNOWN")
        marker = {
            "PASSED": "🟩",
            "EXPECTED_SKIP": "⬜",
            "PENDING": "🟨",
            "FAILED": "🟥",
            "MISSING": "🟥",
            "UNEXPECTED_SKIP": "🟥",
        }.get(state, "⬜")
        requirement = "required" if check.get("required") else "observed"
        lines.append(
            f"{marker} **{check.get('name')}** — {state} ({requirement}; {check.get('detail')})"
        )
    return "\n".join(lines) + "\n"
