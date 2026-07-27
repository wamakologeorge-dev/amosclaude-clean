"""Amosclaud Hub Compiler.

The Hub Compiler turns the activity the platform already records into
polished, reviewable project artifacts. This package is the home for every
compiler capability; the first one is the **Project Report Card**
(:mod:`amoscloud_ai.hub.report`), which aggregates recorded GitHub App
webhook events for a repository and a date range into sanitized Markdown
plus rendered HTML. The second is the **Visual Architecture Mapper**
(:mod:`amoscloud_ai.hub.architecture`), which statically analyses a repository
working tree and draws it as Mermaid — with no model call at all.

Design rules for anything added here:

* deterministic content first — counts, tables and lists must never depend on
  a model being reachable;
* the first-party model layer (:mod:`amoscloud_ai.provider`) is a best-effort
  enhancement with a bounded timeout and an honest fallback;
* untrusted webhook text is escaped before it reaches Markdown, and HTML is
  always produced through :mod:`amoscloud_ai.markdown_service`.
"""

from __future__ import annotations

from amoscloud_ai.hub.architecture import (
    ArchitectureDocument,
    ArchitectureMap,
    ArchitectureScanError,
    MermaidGraph,
    PackageUnit,
    PythonModule,
    RouteEndpoint,
    RouterDefinition,
    SkippedFile,
    TableDefinition,
    build_architecture_document,
    build_package_diagram,
    build_route_diagram,
    escape_mermaid_label,
    render_architecture_markdown,
    scan_architecture,
)
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
    "ArchitectureDocument",
    "ArchitectureMap",
    "ArchitectureScanError",
    "ClosedIssue",
    "Contributor",
    "MergedPullRequest",
    "MermaidGraph",
    "Narrative",
    "PackageUnit",
    "PushActivity",
    "PythonModule",
    "ReportCard",
    "RepositoryActivity",
    "RouteEndpoint",
    "RouterDefinition",
    "SkippedFile",
    "TableDefinition",
    "aggregate_activity",
    "build_architecture_document",
    "build_package_diagram",
    "build_report_card",
    "build_route_diagram",
    "default_window",
    "draft_narrative",
    "escape_mermaid_label",
    "narrative_facts",
    "render_architecture_markdown",
    "render_report_markdown",
    "scan_architecture",
]
