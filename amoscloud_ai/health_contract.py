"""Deterministic workflow health classification for Amosclaud.

A repository is verified only when every required check is present and every
observed check has an accepted conclusion. Conditional skips must be declared
for the concrete event that produced the check. Missing, pending, cancelled,
or unexpectedly skipped checks remain visible and prevent a 100% claim.
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
    display_name: str
    state: str
    conclusion: str | None
    required: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "display_name": self.display_name,
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
                    display_name=name,
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

    has_blocker = any(
        state.state in {"FAILED", "UNEXPECTED_SKIP", "UNKNOWN"}
        or (state.required and state.state == "MISSING")
        for state in states
    )
    has_pending = any(state.state == "PENDING" for state in states)
    all_required_verified = all(
        state.state in {"PASSED", "EXPECTED_SKIP"} for state in states if state.required
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
        1 for state in states if state.required and state.state in {"PASSED", "EXPECTED_SKIP"}
    )
    observed_total = len(states)
    observed_verified = sum(1 for state in states if state.state in {"PASSED", "EXPECTED_SKIP"})
    percentage = round((observed_verified / observed_total) * 100) if observed_total else 0
    truthful_100_percent = overall == "VERIFIED" and percentage == 100
    if not truthful_100_percent and percentage == 100:
        percentage = 99

    return {
        "schema": "amosclaud.health-contract.v1",
        "overall": overall,
        "percentage": percentage,
        "required_total": required_total,
        "required_verified": required_verified,
        "observed_total": observed_total,
        "observed_verified": observed_verified,
        "counts": counts,
        "checks": [state.as_dict() for state in states],
        "exit_code": exit_code,
        "truthful_100_percent": truthful_100_percent,
    }


def _classify(
    name: str,
    check: Mapping[str, object],
    *,
    required: bool,
    expected_skips: Sequence[str],
) -> CheckState:
    display_name = str(check.get("display_name") or name).strip() or name
    status = str(check.get("status") or "").strip().lower()
    raw_conclusion = check.get("conclusion")
    conclusion = str(raw_conclusion).strip().lower() if raw_conclusion is not None else None

    if status in PENDING_STATUSES or (status != "completed" and conclusion is None):
        return CheckState(
            name,
            display_name,
            "PENDING",
            conclusion,
            required,
            f"status={status or 'unknown'}",
        )
    if conclusion in PASSING_CONCLUSIONS:
        return CheckState(
            name,
            display_name,
            "PASSED",
            conclusion,
            required,
            f"conclusion={conclusion}",
        )
    if conclusion == "skipped":
        skip_expected = bool(check.get("skip_expected")) or _matches(display_name, expected_skips)
        if skip_expected:
            event = str(check.get("event") or "unknown")
            return CheckState(
                name,
                display_name,
                "EXPECTED_SKIP",
                conclusion,
                required,
                f"conditional check was allowed to skip for event={event}",
            )
        return CheckState(
            name,
            display_name,
            "UNEXPECTED_SKIP",
            conclusion,
            required,
            "skip was not declared by the event contract",
        )
    if conclusion in FAILING_CONCLUSIONS:
        return CheckState(
            name,
            display_name,
            "FAILED",
            conclusion,
            required,
            f"conclusion={conclusion}",
        )
    return CheckState(
        name,
        display_name,
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
        f"**Observed verification:** {percentage}%",
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
        display_name = check.get("display_name") or check.get("name")
        lines.append(
            f"{marker} **{display_name}** — {state} " f"({requirement}; {check.get('detail')})"
        )
    return "\n".join(lines) + "\n"
