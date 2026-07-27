"""Amosclaud Hub Compiler.

The Hub Compiler turns the activity the platform already records into
polished, reviewable project artifacts. This package is the home for every
compiler capability; the first one is the **Project Report Card**
(:mod:`amoscloud_ai.hub.report`), which aggregates recorded GitHub App
webhook events for a repository and a date range into sanitized Markdown
plus rendered HTML.

Design rules for anything added here:

* deterministic content first — counts, tables and lists must never depend on
  a model being reachable;
* the first-party model layer (:mod:`amoscloud_ai.provider`) is a best-effort
  enhancement with a bounded timeout and an honest fallback;
* untrusted webhook text is escaped before it reaches Markdown, and HTML is
  always produced through :mod:`amoscloud_ai.markdown_service`.
"""

from __future__ import annotations

from amoscloud_ai.hub.report import (
    ClosedIssue,
    Contributor,
    MergedPullRequest,
    Narrative,
    PushActivity,
    ReportCard,
    RepositoryActivity,
    aggregate_activity,
    build_report_card,
    default_window,
    draft_narrative,
    narrative_facts,
    render_report_markdown,
)

__all__ = [
    "ClosedIssue",
    "Contributor",
    "MergedPullRequest",
    "Narrative",
    "PushActivity",
    "ReportCard",
    "RepositoryActivity",
    "aggregate_activity",
    "build_report_card",
    "default_window",
    "draft_narrative",
    "narrative_facts",
    "render_report_markdown",
]
