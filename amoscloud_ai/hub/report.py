"""Project Report Card compiler.

Aggregates the GitHub activity the platform has already recorded into a
polished report for one repository and one date range.

Data source (verified against :mod:`amoscloud_ai.api.routes.github_app`)
-----------------------------------------------------------------------
The inbound GitHub App webhook writes one row per delivery into the SQLite
table ``github_events`` with columns
``id, delivery_id, event, action, repository, sender, summary, received_at``.
The connection is opened by ``github_app._connect()``, which honours the
``AMOSCLAUD_GITHUB_EVENTS_DB`` environment variable and creates the table if
it does not exist yet; this module reuses that helper instead of hardcoding a
path.

Two properties of that writer matter here:

* ``received_at`` is ``datetime.now(timezone.utc).isoformat()``.
* For ``pull_request`` deliveries the ``action`` column stores the *derived
  state* from ``github_app._summarise()``: it is ``"merged"`` only when the
  payload said ``action == "closed"`` **and** ``pull_request.merged`` was
  true. A pull request that was closed without merging is stored as
  ``"closed"``. This module therefore counts a merge only for the literal
  ``"merged"`` state and never treats ``"closed"`` as a merge.

The raw webhook payload is **not** persisted, so every field below is either a
real column or is parsed defensively out of the ``summary`` text the webhook
composed. Pull request titles are not present in ``github_events`` at all;
they are recovered on a best-effort basis from the codex memory entry the same
webhook writes (``amoscloud_ai.codex_memory``), and their absence never fails
a report.
"""

from __future__ import annotations

import os
import queue
import re
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from amoscloud_ai import codex_memory, provider
from amoscloud_ai.markdown_service import MarkdownDocument, render_markdown_document

EVENTS_TABLE = "github_events"

#: Hard ceiling on rows pulled from ``github_events`` for one report.
MAX_EVENT_ROWS = 20_000

#: Longest window a single report may cover.
MAX_WINDOW_DAYS = 366

#: Default window when the caller does not supply one.
DEFAULT_WINDOW_DAYS = 7

#: Hard cap on the characters handed to the model. The report never sends raw
#: event JSON; only a distilled digest of the aggregate.
MAX_PROMPT_CHARACTERS = 1_200

#: Default bounded wait for the optional model narrative. The shared model
#: runtime has been observed taking minutes on large prompts, so the report
#: gives it a short budget and moves on.
DEFAULT_NARRATIVE_TIMEOUT_SECONDS = 20.0

_NARRATIVE_SYSTEM_PROMPT = (
    "You write short factual engineering status notes. Use only the facts "
    "given. Never invent numbers, names or work that is not listed. Reply "
    "with two to four plain sentences and no markdown, no headings and no "
    "bullet points."
)

_MAX_CELL_CHARACTERS = 200
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PULL_REQUEST_SUMMARY = re.compile(
    r"Pull request #(?P<number>\d+)\s+(?P<state>\S+)(?:\s+by\s+(?P<author>[^\s(]+))?",
)
_ISSUE_SUMMARY = re.compile(
    r"Issue #(?P<number>\d+)\s+(?P<action>[^:]*):\s*(?P<title>.*)",
    re.DOTALL,
)
_PUSH_SUMMARY = re.compile(
    r"pushed\s+(?P<commits>\d+)\s+commit\(s\)\s+to\s+(?P<branch>.+?)\.\s+Head:",
    re.DOTALL,
)
_CODEX_PULL_REQUEST_TITLE = re.compile(
    r"PR #(?P<number>\d+)\s+(?P<state>\S+):\s*(?P<title>.*)",
    re.DOTALL,
)
_ANY_NUMBER = re.compile(r"#(\d+)")


class HubReportError(ValueError):
    """Raised when a report request is not answerable as asked."""


# ---------------------------------------------------------------------------
# structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergedPullRequest:
    """One pull request whose recorded state was a genuine merge."""

    number: int
    title: str
    author: str
    merged_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "author": self.author,
            "merged_at": self.merged_at.isoformat(),
        }


@dataclass(frozen=True)
class ClosedIssue:
    """One issue recorded as closed inside the window."""

    number: int
    title: str
    author: str
    closed_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "author": self.author,
            "closed_at": self.closed_at.isoformat(),
        }


@dataclass(frozen=True)
class PushActivity:
    """Commit delivery activity, counted from ``push`` events."""

    pushes: int = 0
    commits: int = 0
    branches: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "pushes": self.pushes,
            "commits": self.commits,
            "branches": list(self.branches),
        }


@dataclass(frozen=True)
class Contributor:
    """Per-person activity counts inside the window."""

    login: str
    merged_pull_requests: int = 0
    closed_issues: int = 0
    pushes: int = 0
    commits: int = 0

    @property
    def total(self) -> int:
        return self.merged_pull_requests + self.closed_issues + self.pushes

    def to_dict(self) -> dict[str, object]:
        return {
            "login": self.login,
            "merged_pull_requests": self.merged_pull_requests,
            "closed_issues": self.closed_issues,
            "pushes": self.pushes,
            "commits": self.commits,
            "total": self.total,
        }


@dataclass(frozen=True)
class RepositoryActivity:
    """Deterministic aggregate of recorded activity for one window."""

    repository: str
    since: datetime
    until: datetime
    merged_pull_requests: tuple[MergedPullRequest, ...] = ()
    closed_issues: tuple[ClosedIssue, ...] = ()
    push_activity: PushActivity = field(default_factory=PushActivity)
    contributors: tuple[Contributor, ...] = ()
    event_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    truncated: bool = False

    @property
    def merged_pull_request_count(self) -> int:
        return len(self.merged_pull_requests)

    @property
    def closed_issue_count(self) -> int:
        return len(self.closed_issues)

    @property
    def contributor_count(self) -> int:
        return len(self.contributors)

    @property
    def has_activity(self) -> bool:
        return bool(
            self.merged_pull_requests
            or self.closed_issues
            or self.push_activity.pushes
            or self.event_count
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "repository": self.repository,
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "merged_pull_requests": [item.to_dict() for item in self.merged_pull_requests],
            "closed_issues": [item.to_dict() for item in self.closed_issues],
            "push_activity": self.push_activity.to_dict(),
            "contributors": [item.to_dict() for item in self.contributors],
            "counts": {
                "merged_pull_requests": self.merged_pull_request_count,
                "closed_issues": self.closed_issue_count,
                "pushes": self.push_activity.pushes,
                "commits": self.push_activity.commits,
                "contributors": self.contributor_count,
                "events": self.event_count,
            },
            "first_event_at": self.first_event_at.isoformat() if self.first_event_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class Narrative:
    """The short prose summary and an honest record of where it came from."""

    text: str
    source: str  # "model" or "deterministic"
    reason: str | None = None
    model: str | None = None

    @property
    def model_drafted(self) -> bool:
        return self.source == "model"

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "source": self.source,
            "model_drafted": self.model_drafted,
            "reason": self.reason,
            "model": self.model,
        }


@dataclass(frozen=True)
class ReportCard:
    """A finished report: aggregate, narrative, Markdown and sanitized HTML."""

    activity: RepositoryActivity
    narrative: Narrative
    markdown: str
    html: str
    source_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "activity": self.activity.to_dict(),
            "narrative": self.narrative.to_dict(),
            "markdown": self.markdown,
            "html": self.html,
            "source_sha256": self.source_sha256,
        }


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------


def to_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime.

    Naive datetimes are treated as UTC rather than local time so a report is
    reproducible on any host.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timestamp(value: object) -> datetime | None:
    """Parse a stored ``received_at`` value into aware UTC, or ``None``."""

    if isinstance(value, datetime):
        return to_utc(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return to_utc(parsed)


def default_window(
    since: datetime | None = None,
    until: datetime | None = None,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve an inclusive ``(since, until)`` window, defaulting to 7 days."""

    reference = to_utc(now) if now else datetime.now(timezone.utc)
    resolved_until = to_utc(until) if until else reference
    resolved_since = (
        to_utc(since)
        if since
        else resolved_until - timedelta(days=DEFAULT_WINDOW_DAYS)
    )
    if resolved_since > resolved_until:
        raise HubReportError("since must not be later than until")
    if resolved_until - resolved_since > timedelta(days=MAX_WINDOW_DAYS):
        raise HubReportError(f"the reporting window may not exceed {MAX_WINDOW_DAYS} days")
    return resolved_since, resolved_until


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def _events_connection() -> sqlite3.Connection:
    # Imported lazily: the route module owns the HTTP surface and importing it
    # at module scope would tie this library to FastAPI import order.
    from amoscloud_ai.api.routes.github_app import _connect

    return _connect()


def _row_value(row: sqlite3.Row, column: str) -> str:
    try:
        value = row[column]
    except (IndexError, KeyError):
        return ""
    return str(value or "").strip()


def _pull_request_titles(repository: str) -> dict[int, str]:
    """Best-effort pull request titles from codex memory.

    ``github_events.summary`` does not carry the pull request title, but the
    same webhook stores a codex entry titled ``PR #12 merged: <title>``. A
    missing, empty or unreadable codex volume simply yields no titles.
    """

    titles: dict[int, str] = {}
    merged_seen: set[int] = set()
    try:
        memory = codex_memory.get_codex_memory()
        database = memory.database
        if not database.exists():
            return titles
        with sqlite3.connect(database) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """SELECT title FROM memories
                   WHERE project = ? AND kind = 'event' AND title LIKE 'PR #%'
                   ORDER BY created_at ASC""",
                (codex_memory.normalise_volume(repository),),
            ).fetchall()
    except (sqlite3.Error, OSError, AttributeError, ValueError):
        return titles
    for row in rows:
        match = _CODEX_PULL_REQUEST_TITLE.match(str(row["title"] or "").strip())
        if not match:
            continue
        try:
            number = int(match.group("number"))
        except (TypeError, ValueError):
            continue
        title = match.group("title").strip()
        if not title:
            continue
        merged = match.group("state").strip().lower() == "merged"
        if number in merged_seen and not merged:
            continue
        if merged:
            merged_seen.add(number)
        titles[number] = title
    return titles


def _fetch_rows(
    connection: sqlite3.Connection,
    repository: str,
    limit: int,
) -> list[sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    return connection.execute(
        f"""SELECT event, action, repository, sender, summary, received_at
            FROM {EVENTS_TABLE}
            WHERE repository = ? COLLATE NOCASE
            ORDER BY received_at DESC
            LIMIT ?""",
        (repository, max(1, limit)),
    ).fetchall()


def aggregate_activity(
    *,
    repository: str,
    since: datetime,
    until: datetime,
    connection: sqlite3.Connection | None = None,
    limit: int = MAX_EVENT_ROWS,
) -> RepositoryActivity:
    """Aggregate recorded webhook events for one repository and window.

    ``since`` and ``until`` are both **inclusive** and are normalised to UTC.
    An empty window is not an error: the returned aggregate simply reports no
    activity.
    """

    name = (repository or "").strip()
    if not name:
        raise HubReportError("a repository full name is required")
    window_since = to_utc(since)
    window_until = to_utc(until)
    if window_since > window_until:
        raise HubReportError("since must not be later than until")

    owns_connection = connection is None
    database = connection or _events_connection()
    try:
        rows = _fetch_rows(database, name, limit)
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        raise HubReportError(f"recorded GitHub events are unavailable: {exc}") from exc
    finally:
        if owns_connection:
            database.close()

    merged: dict[int, MergedPullRequest] = {}
    issues: dict[int, ClosedIssue] = {}
    pushes = 0
    commits = 0
    branches: list[str] = []
    counters: dict[str, dict[str, int]] = defaultdict(
        lambda: {"merged": 0, "issues": 0, "pushes": 0, "commits": 0}
    )
    considered = 0
    first_at: datetime | None = None
    last_at: datetime | None = None

    for row in rows:
        received_at = parse_timestamp(_row_value(row, "received_at"))
        if received_at is None or received_at < window_since or received_at > window_until:
            continue
        considered += 1
        first_at = received_at if first_at is None or received_at < first_at else first_at
        last_at = received_at if last_at is None or received_at > last_at else last_at

        event = _row_value(row, "event").lower()
        action = _row_value(row, "action").lower()
        summary = _row_value(row, "summary")
        sender = _row_value(row, "sender")

        if event == "pull_request":
            # Only the derived "merged" state counts. "closed" means closed
            # without merging and is deliberately excluded.
            if action != "merged":
                continue
            number, author = _parse_pull_request(summary)
            if number is None:
                continue
            author = author or sender or "unknown"
            existing = merged.get(number)
            if existing is not None and existing.merged_at >= received_at:
                continue
            merged[number] = MergedPullRequest(
                number=number,
                title="",
                author=author,
                merged_at=received_at,
            )
        elif event == "issues":
            if action != "closed":
                continue
            number, title = _parse_issue(summary)
            if number is None:
                continue
            existing_issue = issues.get(number)
            if existing_issue is not None and existing_issue.closed_at >= received_at:
                continue
            issues[number] = ClosedIssue(
                number=number,
                title=title,
                author=sender or "unknown",
                closed_at=received_at,
            )
        elif event == "push":
            pushed_commits, branch = _parse_push(summary)
            pushes += 1
            commits += pushed_commits
            if branch and branch not in branches:
                branches.append(branch)
            actor = sender or "unknown"
            counters[actor]["pushes"] += 1
            counters[actor]["commits"] += pushed_commits

    for item in merged.values():
        counters[item.author]["merged"] += 1
    for issue in issues.values():
        counters[issue.author]["issues"] += 1

    titles = _pull_request_titles(name) if merged else {}
    merged_list = tuple(
        sorted(
            (
                MergedPullRequest(
                    number=item.number,
                    title=titles.get(item.number, ""),
                    author=item.author,
                    merged_at=item.merged_at,
                )
                for item in merged.values()
            ),
            key=lambda item: (item.merged_at, item.number),
            reverse=True,
        )
    )
    issue_list = tuple(
        sorted(issues.values(), key=lambda item: (item.closed_at, item.number), reverse=True)
    )
    contributors = tuple(
        sorted(
            (
                Contributor(
                    login=login,
                    merged_pull_requests=values["merged"],
                    closed_issues=values["issues"],
                    pushes=values["pushes"],
                    commits=values["commits"],
                )
                for login, values in counters.items()
                if login
            ),
            key=lambda item: (-item.total, -item.commits, item.login.lower()),
        )
    )
    return RepositoryActivity(
        repository=name,
        since=window_since,
        until=window_until,
        merged_pull_requests=merged_list,
        closed_issues=issue_list,
        push_activity=PushActivity(
            pushes=pushes, commits=commits, branches=tuple(branches)
        ),
        contributors=contributors,
        event_count=considered,
        first_event_at=first_at,
        last_event_at=last_at,
        truncated=len(rows) >= max(1, limit),
    )


def _parse_pull_request(summary: str) -> tuple[int | None, str]:
    match = _PULL_REQUEST_SUMMARY.search(summary)
    if match:
        try:
            return int(match.group("number")), (match.group("author") or "").strip()
        except (TypeError, ValueError):
            return None, ""
    fallback = _ANY_NUMBER.search(summary)
    if fallback:
        try:
            return int(fallback.group(1)), ""
        except (TypeError, ValueError):
            return None, ""
    return None, ""


def _parse_issue(summary: str) -> tuple[int | None, str]:
    match = _ISSUE_SUMMARY.search(summary)
    if match:
        try:
            return int(match.group("number")), match.group("title").strip()
        except (TypeError, ValueError):
            return None, ""
    fallback = _ANY_NUMBER.search(summary)
    if fallback:
        try:
            return int(fallback.group(1)), ""
        except (TypeError, ValueError):
            return None, ""
    return None, ""


def _parse_push(summary: str) -> tuple[int, str]:
    match = _PUSH_SUMMARY.search(summary)
    if not match:
        return 0, ""
    try:
        commits = int(match.group("commits"))
    except (TypeError, ValueError):
        commits = 0
    return max(0, commits), match.group("branch").strip()


# ---------------------------------------------------------------------------
# narrative (optional model enhancement)
# ---------------------------------------------------------------------------


def _narrative_timeout() -> float:
    raw = os.getenv("AMOSCLAUD_HUB_NARRATIVE_TIMEOUT", "").strip()
    try:
        configured = float(raw) if raw else DEFAULT_NARRATIVE_TIMEOUT_SECONDS
    except ValueError:
        configured = DEFAULT_NARRATIVE_TIMEOUT_SECONDS
    return min(max(configured, 1.0), 120.0)


def _window_label(activity: RepositoryActivity) -> str:
    return (
        f"{activity.since.strftime('%Y-%m-%d %H:%M')} to "
        f"{activity.until.strftime('%Y-%m-%d %H:%M')} UTC"
    )


def narrative_facts(activity: RepositoryActivity) -> str:
    """Distil the aggregate into a compact fact sheet for the model.

    Raw event JSON is never sent. The result is hard-capped at
    :data:`MAX_PROMPT_CHARACTERS` characters.
    """

    lines = [
        f"repository: {activity.repository}",
        f"window: {_window_label(activity)}",
        f"merged pull requests: {activity.merged_pull_request_count}",
        f"closed issues: {activity.closed_issue_count}",
        f"pushes: {activity.push_activity.pushes}",
        f"commits pushed: {activity.push_activity.commits}",
        f"contributors: {activity.contributor_count}",
    ]
    top = ", ".join(
        f"{item.login} ({item.total})" for item in activity.contributors[:5]
    )
    if top:
        lines.append(f"most active: {top}")
    for item in activity.merged_pull_requests[:5]:
        label = item.title or "(title not recorded)"
        lines.append(f"merged PR #{item.number}: {label[:80]} by {item.author}")
    for item in activity.closed_issues[:5]:
        label = item.title or "(title not recorded)"
        lines.append(f"closed issue #{item.number}: {label[:80]}")
    facts = "\n".join(lines)
    return facts[:MAX_PROMPT_CHARACTERS]


def deterministic_narrative(activity: RepositoryActivity, reason: str | None = None) -> str:
    """A truthful summary sentence built without any model call."""

    if not activity.has_activity:
        sentence = (
            f"No GitHub activity was recorded for {activity.repository} during "
            f"{_window_label(activity)}."
        )
    else:
        sentence = (
            f"During {_window_label(activity)}, {activity.repository} recorded "
            f"{activity.merged_pull_request_count} merged pull request(s), "
            f"{activity.closed_issue_count} closed issue(s) and "
            f"{activity.push_activity.pushes} push(es) carrying "
            f"{activity.push_activity.commits} commit(s) from "
            f"{activity.contributor_count} contributor(s)."
        )
    if reason:
        sentence += (
            f" A model-drafted narrative was not available ({reason}); every "
            "figure in this report is counted directly from recorded events."
        )
    return sentence


def _call_provider(facts: str, timeout: float) -> tuple[object | None, str | None]:
    """Run ``provider.reply`` with a bounded wait.

    The provider client is synchronous and its own timeout budget can run into
    minutes, so the call happens on a daemon thread that is abandoned when the
    budget expires. Abandoning it never blocks the caller or the event loop.
    """

    outcome: queue.Queue[tuple[object | None, str | None]] = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            result = provider.reply(
                [{"role": "user", "content": facts}],
                _NARRATIVE_SYSTEM_PROMPT,
            )
        except BaseException as exc:  # noqa: BLE001 - never propagate to a report
            outcome.put((None, f"the model layer raised {type(exc).__name__}"))
            return
        outcome.put((result, None))

    threading.Thread(target=_run, name="hub-narrative", daemon=True).start()
    try:
        return outcome.get(timeout=timeout)
    except queue.Empty:
        return None, f"the model did not answer within {timeout:.0f}s"


def draft_narrative(
    activity: RepositoryActivity,
    *,
    timeout_seconds: float | None = None,
) -> Narrative:
    """Draft the narrative through the first-party provider, best effort.

    The model is strictly optional. Every failure mode — unconfigured
    provider, timeout, raised exception, degraded result, empty reply —
    returns a deterministic narrative with an honest reason instead of raising
    or fabricating prose.
    """

    try:
        configured = bool(provider.is_configured())
    except Exception as exc:  # noqa: BLE001 - readiness checks must not fail a report
        return Narrative(
            text=deterministic_narrative(
                activity, f"the model readiness check raised {type(exc).__name__}"
            ),
            source="deterministic",
            reason=f"the model readiness check raised {type(exc).__name__}",
        )
    if not configured:
        reason = "no first-party model runtime is configured"
        return Narrative(
            text=deterministic_narrative(activity, reason),
            source="deterministic",
            reason=reason,
        )

    timeout = float(timeout_seconds) if timeout_seconds else _narrative_timeout()
    result, failure = _call_provider(narrative_facts(activity), timeout)
    if failure or result is None:
        reason = failure or "the model returned no result"
        return Narrative(
            text=deterministic_narrative(activity, reason),
            source="deterministic",
            reason=reason,
        )

    text = str(getattr(result, "reply", "") or "").strip()
    ok = bool(getattr(result, "ok", False))
    if not ok or not text:
        detail = str(getattr(result, "error", "") or "").strip()
        reason = (
            f"the model reply was unusable: {detail[:160]}"
            if detail
            else "the model returned an empty reply"
        )
        return Narrative(
            text=deterministic_narrative(activity, reason),
            source="deterministic",
            reason=reason,
        )
    return Narrative(
        text=" ".join(text.split())[:1200],
        source="model",
        model=str(getattr(result, "model", "") or "") or None,
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def escape_cell(value: object, *, limit: int = _MAX_CELL_CHARACTERS) -> str:
    """Make untrusted webhook text safe inside a Markdown table cell.

    Titles and logins come straight from GitHub payloads. Newlines and pipes
    would break the table structure, control characters corrupt output, and
    Markdown emphasis characters let a title reshape the document, so all of
    them are neutralised here. HTML is *additionally* neutralised downstream:
    :func:`amoscloud_ai.markdown_service.render_markdown_document` parses with
    ``html=False`` and then sanitises with bleach.
    """

    text = "" if value is None else str(value)
    text = _CONTROL_CHARACTERS.sub("", text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = f"{text[: limit - 1].rstrip()}…"
    for character in ("\\", "|", "`", "*", "_", "[", "]", "<", ">"):
        text = text.replace(character, f"\\{character}")
    return text or "—"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        f"| {' | '.join(header)} |",
        f"| {' | '.join('---' for _ in header)} |",
    ]
    lines.extend(f"| {' | '.join(row)} |" for row in rows)
    return lines


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def render_report_markdown(activity: RepositoryActivity, narrative: Narrative) -> str:
    """Compose the report as Markdown. Deterministic and model-independent."""

    push = activity.push_activity
    lines: list[str] = [
        f"# Project Report Card — {escape_cell(activity.repository, limit=120)}",
        "",
        (
            f"**Period:** {_timestamp(activity.since)} → {_timestamp(activity.until)} UTC  "
        ),
        (
            f"**Recorded events:** {activity.event_count}  "
        ),
        "",
        "## Summary",
        "",
        escape_cell(narrative.text, limit=1200),
        "",
        "## Metrics",
        "",
    ]
    lines.extend(
        _table(
            ["Metric", "Count"],
            [
                ["Merged pull requests", str(activity.merged_pull_request_count)],
                ["Closed issues", str(activity.closed_issue_count)],
                ["Pushes", str(push.pushes)],
                ["Commits pushed", str(push.commits)],
                ["Contributors", str(activity.contributor_count)],
            ],
        )
    )
    lines.extend(["", "## Merged pull requests", ""])
    if activity.merged_pull_requests:
        lines.extend(
            _table(
                ["Pull request", "Title", "Author", "Merged (UTC)"],
                [
                    [
                        f"\\#{item.number}",
                        escape_cell(item.title or "(title not recorded)"),
                        escape_cell(item.author),
                        _timestamp(item.merged_at),
                    ]
                    for item in activity.merged_pull_requests
                ],
            )
        )
    else:
        lines.append("No pull requests were merged in this period.")
    lines.extend(["", "## Closed issues", ""])
    if activity.closed_issues:
        lines.extend(
            _table(
                ["Issue", "Title", "Closed by", "Closed (UTC)"],
                [
                    [
                        f"\\#{item.number}",
                        escape_cell(item.title or "(title not recorded)"),
                        escape_cell(item.author),
                        _timestamp(item.closed_at),
                    ]
                    for item in activity.closed_issues
                ],
            )
        )
    else:
        lines.append("No issues were closed in this period.")
    lines.extend(["", "## Contributors", ""])
    if activity.contributors:
        lines.extend(
            _table(
                ["Contributor", "Merged PRs", "Closed issues", "Pushes", "Commits"],
                [
                    [
                        escape_cell(item.login, limit=120),
                        str(item.merged_pull_requests),
                        str(item.closed_issues),
                        str(item.pushes),
                        str(item.commits),
                    ]
                    for item in activity.contributors
                ],
            )
        )
    else:
        lines.append("No contributor activity was recorded in this period.")
    if push.branches:
        branches = ", ".join(escape_cell(branch, limit=80) for branch in push.branches[:20])
        lines.extend(["", f"**Branches receiving pushes:** {branches}"])
    if activity.truncated:
        lines.extend(
            [
                "",
                (
                    "> This report reached the recorded-event read limit of "
                    f"{MAX_EVENT_ROWS}; older events in the window were not read."
                ),
            ]
        )
    provenance = (
        "model-drafted narrative"
        if narrative.model_drafted
        else "deterministic narrative (model unavailable)"
    )
    lines.extend(
        [
            "",
            "---",
            "",
            (
                "*Compiled by the Amosclaud Hub Compiler from recorded GitHub App "
                f"webhook events · {provenance}.*"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def build_report_card(
    *,
    repository: str,
    repository_id: int,
    since: datetime | None = None,
    until: datetime | None = None,
    connection: sqlite3.Connection | None = None,
    narrative_timeout_seconds: float | None = None,
    include_narrative: bool = True,
) -> ReportCard:
    """Aggregate, narrate (best effort) and render one report card."""

    window_since, window_until = default_window(since, until)
    activity = aggregate_activity(
        repository=repository,
        since=window_since,
        until=window_until,
        connection=connection,
    )
    if include_narrative:
        narrative = draft_narrative(activity, timeout_seconds=narrative_timeout_seconds)
    else:
        reason = "narrative drafting was disabled for this request"
        narrative = Narrative(
            text=deterministic_narrative(activity, reason),
            source="deterministic",
            reason=reason,
        )
    markdown = render_report_markdown(activity, narrative)
    document: MarkdownDocument = render_markdown_document(
        markdown,
        repository_id=repository_id,
        branch="main",
        source_path="hub/report-card.md",
    )
    return ReportCard(
        activity=activity,
        narrative=narrative,
        markdown=markdown,
        html=document.html,
        source_sha256=document.source_sha256,
    )
