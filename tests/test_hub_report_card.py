"""Contract tests for the Hub Compiler project report card.

Covers the aggregation rules (merge detection, deduplication, window
boundaries, empty windows), the four model-optional narrative paths, the
sanitization guarantee for untrusted webhook titles, and the authorization of
the read-only HTTP route. No test performs a network call or needs a live
model runtime.
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amoscloud_ai import codex_memory, provider
from amoscloud_ai.api.routes import auth, github_app, repositories
from amoscloud_ai.db_migrations import ensure_github_repository_schema
from amoscloud_ai.hub import report as hub_report
from amoscloud_ai.main import create_app
from amoscloud_ai.model_api_response import ModelApiResponse

REPOSITORY = "wamakologeorge-dev/amosclaude-clean"
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_hub_storage(tmp_path, monkeypatch):
    """Point every datastore this feature reads at throwaway paths."""

    monkeypatch.setenv("AMOSCLAUD_GITHUB_EVENTS_DB", str(tmp_path / "events.db"))
    monkeypatch.setenv("AMOSCLAUD_CODEX_MEMORY_DIR", str(tmp_path / "codex"))
    codex_memory.reset_cache_for_tests()
    yield
    codex_memory.reset_cache_for_tests()


def record_event(
    *,
    event: str,
    action: str,
    summary: str,
    received_at: datetime,
    repository: str = REPOSITORY,
    sender: str = "wamakologeorge-dev",
) -> None:
    """Insert one row exactly as ``github_app.receive_webhook`` would."""

    with github_app._connect() as db:
        db.execute(
            """INSERT INTO github_events
               (id, delivery_id, event, action, repository, sender, summary, received_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                f"ghe_{uuid.uuid4().hex[:20]}",
                uuid.uuid4().hex[:12],
                event,
                action,
                repository,
                sender,
                summary,
                received_at.isoformat(),
            ),
        )


def merged_pull_request_event(
    number: int,
    *,
    author: str = "wamakologeorge-dev",
    when: datetime,
) -> None:
    record_event(
        event="pull_request",
        action="merged",
        summary=(
            f"Pull request #{number} merged by {author} (3 files, +40/-12)"
        ),
        received_at=when,
        sender=author,
    )


def closed_unmerged_pull_request_event(number: int, *, when: datetime) -> None:
    record_event(
        event="pull_request",
        action="closed",
        summary=f"Pull request #{number} closed by someone (1 files, +2/-2)",
        received_at=when,
    )


def closed_issue_event(number: int, title: str, *, when: datetime, sender: str = "octocat") -> None:
    record_event(
        event="issues",
        action="closed",
        summary=f"Issue #{number} closed: {title}",
        received_at=when,
        sender=sender,
    )


def push_event(commits: int, branch: str, *, when: datetime, sender: str = "pusher-one") -> None:
    record_event(
        event="push",
        action="push",
        summary=f"{sender} pushed {commits} commit(s) to {branch}. Head: latest change",
        received_at=when,
        sender=sender,
    )


def aggregate(*, since: datetime | None = None, until: datetime | None = None):
    return hub_report.aggregate_activity(
        repository=REPOSITORY,
        since=since or (NOW - timedelta(days=7)),
        until=until or NOW,
    )


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def test_events_table_and_columns_match_the_webhook_writer():
    """Guard the real data source this feature depends on."""

    with github_app._connect() as db:
        columns = {
            row[1]
            for row in db.execute(f"PRAGMA table_info({hub_report.EVENTS_TABLE})").fetchall()
        }
    assert hub_report.EVENTS_TABLE == "github_events"
    assert {
        "id",
        "delivery_id",
        "event",
        "action",
        "repository",
        "sender",
        "summary",
        "received_at",
    } <= columns


def test_only_genuinely_merged_pull_requests_are_counted():
    merged_pull_request_event(11, when=NOW - timedelta(days=1))
    closed_unmerged_pull_request_event(12, when=NOW - timedelta(days=1))
    record_event(
        event="pull_request",
        action="opened",
        summary="Pull request #13 opened by someone (1 files, +1/-0)",
        received_at=NOW - timedelta(hours=2),
    )

    activity = aggregate()

    assert [item.number for item in activity.merged_pull_requests] == [11]
    assert activity.merged_pull_request_count == 1


def test_repeated_events_for_one_pull_request_and_issue_are_deduplicated():
    merged_pull_request_event(21, when=NOW - timedelta(days=2))
    merged_pull_request_event(21, when=NOW - timedelta(days=1))
    closed_issue_event(31, "First close", when=NOW - timedelta(days=2))
    closed_issue_event(31, "Reopened then closed again", when=NOW - timedelta(hours=3))

    activity = aggregate()

    assert [item.number for item in activity.merged_pull_requests] == [21]
    assert activity.merged_pull_requests[0].merged_at == NOW - timedelta(days=1)
    assert [item.number for item in activity.closed_issues] == [31]
    assert activity.closed_issues[0].title == "Reopened then closed again"


def test_window_boundaries_are_inclusive_and_timezone_normalised():
    since = NOW - timedelta(days=1)
    merged_pull_request_event(41, when=since)  # exactly on the lower bound
    merged_pull_request_event(42, when=since - timedelta(seconds=1))  # just outside
    merged_pull_request_event(43, when=NOW)  # exactly on the upper bound
    # A naive timestamp is treated as UTC, not local time.
    record_event(
        event="pull_request",
        action="merged",
        summary="Pull request #44 merged by naive-clock (1 files, +1/-1)",
        received_at=(NOW - timedelta(hours=1)).replace(tzinfo=None),
    )

    activity = hub_report.aggregate_activity(
        repository=REPOSITORY,
        since=since.replace(tzinfo=None),  # naive input normalises to UTC
        until=NOW,
    )

    assert sorted(item.number for item in activity.merged_pull_requests) == [41, 43, 44]


def test_empty_window_produces_a_valid_no_activity_report(monkeypatch):
    monkeypatch.setattr(provider, "is_configured", lambda: False)

    card = hub_report.build_report_card(
        repository=REPOSITORY,
        repository_id=1,
        since=NOW - timedelta(days=7),
        until=NOW,
    )

    assert card.activity.event_count == 0
    assert card.activity.merged_pull_requests == ()
    assert card.activity.has_activity is False
    assert "No pull requests were merged in this period." in card.markdown
    assert "No issues were closed in this period." in card.markdown
    assert "No GitHub activity was recorded" in card.narrative.text
    assert card.html.strip()


def test_pushes_issues_and_contributors_are_aggregated():
    merged_pull_request_event(51, author="alice", when=NOW - timedelta(days=1))
    merged_pull_request_event(52, author="alice", when=NOW - timedelta(hours=20))
    closed_issue_event(61, "Fix the login bug", when=NOW - timedelta(hours=5), sender="bob")
    push_event(3, "main", when=NOW - timedelta(hours=4), sender="alice")
    push_event(2, "feature/x", when=NOW - timedelta(hours=3), sender="bob")

    activity = aggregate()

    assert activity.push_activity.pushes == 2
    assert activity.push_activity.commits == 5
    assert set(activity.push_activity.branches) == {"main", "feature/x"}
    by_login = {item.login: item for item in activity.contributors}
    assert by_login["alice"].merged_pull_requests == 2
    assert by_login["alice"].commits == 3
    assert by_login["bob"].closed_issues == 1
    assert by_login["bob"].pushes == 1
    assert activity.contributor_count == 2
    assert activity.first_event_at is not None and activity.last_event_at is not None


def test_pull_request_titles_are_recovered_from_codex_memory_best_effort():
    merged_pull_request_event(71, when=NOW - timedelta(hours=6))
    codex_memory.store_entry(
        scope=REPOSITORY,
        kind="event",
        title="PR #71 merged: Recover abandoned model-network claims",
        content="Pull request #71 merged by wamakologeorge-dev",
        tags=["github", "pull_request"],
    )

    activity = aggregate()

    assert activity.merged_pull_requests[0].title == (
        "Recover abandoned model-network claims"
    )


def test_missing_codex_volume_does_not_break_the_report(monkeypatch):
    merged_pull_request_event(72, when=NOW - timedelta(hours=6))

    def _boom():
        raise sqlite3.Error("codex volume unavailable")

    monkeypatch.setattr(codex_memory, "get_codex_memory", _boom)

    activity = aggregate()

    assert activity.merged_pull_requests[0].title == ""


def test_unparseable_and_foreign_rows_are_ignored():
    record_event(
        event="pull_request",
        action="merged",
        summary="totally unexpected summary text",
        received_at=NOW - timedelta(hours=1),
    )
    record_event(
        event="push",
        action="push",
        summary="malformed push line",
        received_at=NOW - timedelta(hours=1),
    )
    merged_pull_request_event(81, when=NOW - timedelta(hours=1))
    record_event(
        event="pull_request",
        action="merged",
        summary="Pull request #99 merged by outsider (1 files, +1/-1)",
        received_at=NOW - timedelta(hours=1),
        repository="someone-else/private-repo",
    )
    record_event(
        event="issues",
        action="closed",
        summary="Issue #7 closed: leaked",
        received_at=NOW - timedelta(hours=1),
        repository="someone-else/private-repo",
    )

    activity = aggregate()

    assert sorted(item.number for item in activity.merged_pull_requests) == [81]
    assert activity.closed_issues == ()
    assert activity.push_activity.pushes == 1
    assert activity.push_activity.commits == 0


def test_since_after_until_is_rejected():
    with pytest.raises(hub_report.HubReportError):
        hub_report.default_window(NOW, NOW - timedelta(days=1))
    with pytest.raises(hub_report.HubReportError):
        hub_report.default_window(NOW - timedelta(days=400), NOW)


def test_default_window_covers_the_last_seven_days():
    since, until = hub_report.default_window(now=NOW)
    assert until == NOW
    assert since == NOW - timedelta(days=7)


# ---------------------------------------------------------------------------
# narrative: the model is strictly optional
# ---------------------------------------------------------------------------


def _activity_with_data():
    merged_pull_request_event(91, author="alice", when=NOW - timedelta(hours=8))
    closed_issue_event(92, "Tighten the webhook guard", when=NOW - timedelta(hours=7))
    push_event(4, "main", when=NOW - timedelta(hours=6))
    return aggregate()


def test_narrative_facts_stay_compact_and_carry_no_raw_json():
    activity = _activity_with_data()
    facts = hub_report.narrative_facts(activity)
    assert len(facts) <= hub_report.MAX_PROMPT_CHARACTERS
    assert "{" not in facts and "}" not in facts
    assert "merged pull requests: 1" in facts


def test_narrative_uses_the_model_when_it_answers(monkeypatch):
    activity = _activity_with_data()
    calls: list[tuple[list[dict[str, str]], str]] = []

    def _reply(history, system_prompt):
        calls.append((history, system_prompt))
        return ModelApiResponse(reply="One pull request landed.", runtime="test-runtime")

    monkeypatch.setattr(provider, "is_configured", lambda: True)
    monkeypatch.setattr(provider, "reply", _reply)

    narrative = hub_report.draft_narrative(activity, timeout_seconds=5)

    assert narrative.source == "model"
    assert narrative.model_drafted is True
    assert narrative.text == "One pull request landed."
    assert len(calls) == 1
    assert len(calls[0][0][0]["content"]) <= hub_report.MAX_PROMPT_CHARACTERS


def test_narrative_falls_back_when_the_model_times_out(monkeypatch):
    activity = _activity_with_data()

    def _slow(history, system_prompt):
        time.sleep(30)
        return ModelApiResponse(reply="too late", runtime="test-runtime")

    monkeypatch.setattr(provider, "is_configured", lambda: True)
    monkeypatch.setattr(provider, "reply", _slow)

    started = time.monotonic()
    narrative = hub_report.draft_narrative(activity, timeout_seconds=1)
    elapsed = time.monotonic() - started

    assert narrative.source == "deterministic"
    assert "did not answer" in (narrative.reason or "")
    assert "1 merged pull request(s)" in narrative.text
    assert elapsed < 10  # the slow call is abandoned, never awaited


def test_narrative_falls_back_when_the_model_raises(monkeypatch):
    activity = _activity_with_data()

    def _raise(history, system_prompt):
        raise RuntimeError("model station unreachable")

    monkeypatch.setattr(provider, "is_configured", lambda: True)
    monkeypatch.setattr(provider, "reply", _raise)

    narrative = hub_report.draft_narrative(activity, timeout_seconds=5)

    assert narrative.source == "deterministic"
    assert "RuntimeError" in (narrative.reason or "")
    assert "closed issue(s)" in narrative.text


def test_narrative_falls_back_when_the_model_returns_empty(monkeypatch):
    activity = _activity_with_data()

    monkeypatch.setattr(provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        provider,
        "reply",
        lambda history, system_prompt: ModelApiResponse(reply="   ", runtime="test-runtime"),
    )

    narrative = hub_report.draft_narrative(activity, timeout_seconds=5)

    assert narrative.source == "deterministic"
    assert "empty reply" in (narrative.reason or "")


def test_narrative_falls_back_on_a_degraded_provider_result(monkeypatch):
    activity = _activity_with_data()

    monkeypatch.setattr(provider, "is_configured", lambda: True)
    monkeypatch.setattr(
        provider,
        "reply",
        lambda history, system_prompt: ModelApiResponse(
            reply="No model runtime is connected.",
            runtime="unconfigured",
            status="degraded",
            error="[unconfigured] no usable route",
        ),
    )

    narrative = hub_report.draft_narrative(activity, timeout_seconds=5)

    assert narrative.source == "deterministic"
    assert "unusable" in (narrative.reason or "")


def test_narrative_skips_the_model_when_no_runtime_is_configured(monkeypatch):
    activity = _activity_with_data()

    def _must_not_be_called(history, system_prompt):  # pragma: no cover
        raise AssertionError("the provider must not be called when unconfigured")

    monkeypatch.setattr(provider, "is_configured", lambda: False)
    monkeypatch.setattr(provider, "reply", _must_not_be_called)

    narrative = hub_report.draft_narrative(activity)

    assert narrative.source == "deterministic"
    assert "no first-party model runtime is configured" in (narrative.reason or "")


def test_deterministic_content_is_present_even_without_a_narrative(monkeypatch):
    _activity_with_data()
    monkeypatch.setattr(provider, "is_configured", lambda: False)

    card = hub_report.build_report_card(
        repository=REPOSITORY,
        repository_id=1,
        since=NOW - timedelta(days=7),
        until=NOW,
    )

    assert "| Merged pull requests | 1 |" in card.markdown
    assert "| Closed issues | 1 |" in card.markdown
    assert "| Commits pushed | 4 |" in card.markdown
    assert "Tighten the webhook guard" in card.markdown
    assert card.narrative.source == "deterministic"


# ---------------------------------------------------------------------------
# sanitization of untrusted webhook text
# ---------------------------------------------------------------------------


def test_malicious_titles_are_neutralised_in_markdown_and_html(monkeypatch):
    monkeypatch.setattr(provider, "is_configured", lambda: False)
    hostile = "<script>alert('xss')</script> | extra | row **boom**"
    closed_issue_event(101, hostile, when=NOW - timedelta(hours=2))
    merged_pull_request_event(
        102, author="<img src=x onerror=alert(1)>", when=NOW - timedelta(hours=1)
    )
    codex_memory.store_entry(
        scope=REPOSITORY,
        kind="event",
        title="PR #102 merged: <b>bold</b> | pipe\nnewline",
        content="Pull request #102 merged",
        tags=["github", "pull_request"],
    )

    card = hub_report.build_report_card(
        repository=REPOSITORY,
        repository_id=1,
        since=NOW - timedelta(days=7),
        until=NOW,
    )

    assert "<script" not in card.html.lower()
    assert "onerror" not in card.html.lower()
    assert "<b>bold</b>" not in card.html
    # Table structure survives: the hostile pipes are escaped, not structural.
    issue_rows = [
        line
        for line in card.markdown.splitlines()
        if line.startswith("| \\#101 ")
    ]
    assert len(issue_rows) == 1
    assert issue_rows[0].count("|") - issue_rows[0].count("\\|") == 5
    # The codex-sourced pull request title also stays on one row.
    pull_request_rows = [
        line for line in card.markdown.splitlines() if line.startswith("| \\#102 ")
    ]
    assert len(pull_request_rows) == 1
    assert pull_request_rows[0].count("|") - pull_request_rows[0].count("\\|") == 5
    assert "bold" in pull_request_rows[0] and "newline" in pull_request_rows[0]


def test_escape_cell_neutralises_structure_breaking_characters():
    assert hub_report.escape_cell("a | b") == "a \\| b"
    assert hub_report.escape_cell("line\nbreak") == "line break"
    assert hub_report.escape_cell("<script>") == "\\<script\\>"
    assert hub_report.escape_cell("") == "—"
    assert hub_report.escape_cell("x" * 500).endswith("…")


# ---------------------------------------------------------------------------
# HTTP route
# ---------------------------------------------------------------------------


def _create_user_and_session(email: str) -> tuple[str, object]:
    token = f"session-{email}"
    now = datetime.now(timezone.utc)
    with auth._connect() as db:
        cursor = db.execute(
            "INSERT INTO users(name,email,password_hash,provider,is_admin,created_at)"
            " VALUES (?,?,?,'password',0,?)",
            (
                email.split("@", 1)[0],
                email,
                auth._hash_password("strong-password"),
                now.isoformat(),
            ),
        )
        user_id = cursor.lastrowid
        db.execute(
            "INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES (?,?,?,?)",
            (
                auth._token_hash(token),
                user_id,
                (now + timedelta(hours=1)).isoformat(),
                now.isoformat(),
            ),
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return token, user


@pytest.fixture
def hosted_repository(tmp_path, monkeypatch):
    database = tmp_path / "auth.db"
    monkeypatch.setattr(auth, "DB_PATH", database)
    monkeypatch.setattr(repositories, "DB_PATH", database)
    monkeypatch.setattr(repositories, "REPOSITORY_ROOT", tmp_path / "repositories")
    monkeypatch.setattr(provider, "is_configured", lambda: False)
    owner_token, owner = _create_user_and_session("owner@example.com")
    repository = repositories.create_repository(
        repositories.RepositoryCreate(name="hub-project", visibility="public"), owner
    )
    return {"token": owner_token, "repository": repository}


def _link_to_github(repository_id: int, full_name: str = REPOSITORY) -> None:
    with repositories._db() as db:
        ensure_github_repository_schema(db)
        db.execute(
            "UPDATE repositories SET github_full_name=?, github_repository_id=? WHERE id=?",
            (full_name, 424242, repository_id),
        )
        db.commit()


def _get(path: str, token: str | None = None) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            if token:
                client.cookies.set(auth.SESSION_COOKIE, token)
            return await client.get(path)

    return asyncio.run(_go())


def test_report_card_requires_authentication(hosted_repository):
    repository_id = hosted_repository["repository"].id
    _link_to_github(repository_id)

    response = _get(f"/api/v1/hub/repositories/{repository_id}/report-card")

    assert response.status_code == 401


def test_report_card_denies_a_user_without_repository_write_access(hosted_repository):
    repository_id = hosted_repository["repository"].id
    _link_to_github(repository_id)
    outsider_token, _ = _create_user_and_session("outsider@example.com")

    response = _get(
        f"/api/v1/hub/repositories/{repository_id}/report-card", token=outsider_token
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Write access required"


def test_report_card_hides_repositories_the_caller_cannot_see(hosted_repository):
    _, other_owner = _create_user_and_session("other-owner@example.com")
    private_repository = repositories.create_repository(
        repositories.RepositoryCreate(name="private-project", visibility="private"),
        other_owner,
    )
    _link_to_github(private_repository.id)

    response = _get(
        f"/api/v1/hub/repositories/{private_repository.id}/report-card",
        token=hosted_repository["token"],
    )

    assert response.status_code == 404


def test_report_card_reports_unlinked_repositories_honestly(hosted_repository):
    repository_id = hosted_repository["repository"].id

    response = _get(
        f"/api/v1/hub/repositories/{repository_id}/report-card",
        token=hosted_repository["token"],
    )

    assert response.status_code == 409
    assert "not linked" in response.json()["detail"]


def test_report_card_returns_summary_markdown_and_html(hosted_repository):
    repository_id = hosted_repository["repository"].id
    _link_to_github(repository_id)
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    merged_pull_request_event(201, author="alice", when=recent)
    closed_issue_event(202, "Harden the report window", when=recent)
    push_event(6, "main", when=recent, sender="alice")

    response = _get(
        f"/api/v1/hub/repositories/{repository_id}/report-card?narrative=false",
        token=hosted_repository["token"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["github_full_name"] == REPOSITORY
    assert body["activity"]["counts"] == {
        "merged_pull_requests": 1,
        "closed_issues": 1,
        "pushes": 1,
        "commits": 6,
        "contributors": 2,
        "events": 3,
    }
    assert body["activity"]["merged_pull_requests"][0]["number"] == 201
    assert body["narrative"]["model_drafted"] is False
    assert "Project Report Card" in body["markdown"]
    assert "<h1" in body["html"]
    assert "Harden the report window" in body["html"]
    assert len(body["source_sha256"]) == 64


def test_report_card_rejects_an_inverted_window(hosted_repository):
    repository_id = hosted_repository["repository"].id
    _link_to_github(repository_id)

    response = _get(
        f"/api/v1/hub/repositories/{repository_id}/report-card"
        "?since=2026-07-27T00:00:00Z&until=2026-07-20T00:00:00Z",
        token=hosted_repository["token"],
    )

    assert response.status_code == 422


def test_report_card_route_is_read_only():
    """Phase 1 must not expose any write surface under /hub."""

    from amoscloud_ai.api.routes import hub_reports

    methods = {
        method
        for route in hub_reports.router.routes
        for method in getattr(route, "methods", set())
    }
    assert methods == {"GET"}
