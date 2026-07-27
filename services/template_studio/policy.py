"""Policy-governed planning templates and AI assistance for Template Studio."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import bleach
import httpx

MAX_TITLE_LENGTH = 160
MAX_CONTENT_LENGTH = 250_000
MAX_INSTRUCTION_LENGTH = 4_000
ALLOWED_STATUSES = {"draft", "active", "blocked", "review", "completed", "archived"}
ALLOWED_KINDS = {"open_source", "business", "marketing", "management", "blank"}
ALLOWED_ACTIONS = {
    "outline", "improve", "summary", "risks", "milestones",
    "open_source", "business", "marketing", "management",
}
_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3", "h4",
    "hr", "img", "li", "ol", "p", "pre", "span", "strong", "table", "tbody",
    "td", "th", "thead", "tr", "u", "ul",
}
_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "div": ["class", "data-shape"],
    "img": ["src", "alt", "title", "width", "height"],
    "span": ["class"], "table": ["class"],
    "td": ["colspan", "rowspan"], "th": ["colspan", "rowspan"],
}
_ALLOWED_PROTOCOLS = ["http", "https", "mailto", "data"]


class TemplatePolicyError(ValueError):
    """Raised when a Template Studio operation violates policy."""


def clean_title(value: str) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()
    if not title:
        raise TemplatePolicyError("Plan title is required")
    if len(title) > MAX_TITLE_LENGTH:
        raise TemplatePolicyError(f"Plan title must be {MAX_TITLE_LENGTH} characters or fewer")
    return title


def clean_kind(value: str) -> str:
    kind = str(value or "blank").strip().lower().replace("-", "_")
    if kind not in ALLOWED_KINDS:
        raise TemplatePolicyError(f"Unsupported plan kind: {kind}")
    return kind


def clean_status(value: str) -> str:
    status = str(value or "draft").strip().lower()
    if status not in ALLOWED_STATUSES:
        raise TemplatePolicyError(f"Unsupported plan status: {status}")
    return status


def clean_progress(value: int | float | str) -> int:
    try:
        progress = int(value)
    except (TypeError, ValueError) as exc:
        raise TemplatePolicyError("Progress must be a number") from exc
    return max(0, min(progress, 100))


def clean_html(value: str) -> str:
    content = str(value or "")
    if len(content) > MAX_CONTENT_LENGTH:
        raise TemplatePolicyError(f"Plan content must be {MAX_CONTENT_LENGTH} characters or fewer")
    return bleach.clean(
        content,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )


def clean_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    metadata = value or {}
    if not isinstance(metadata, dict):
        raise TemplatePolicyError("Metadata must be an object")
    encoded = json.dumps(metadata, ensure_ascii=False)
    if len(encoded) > 50_000:
        raise TemplatePolicyError("Metadata is too large")
    return json.loads(encoded)


def template_catalog() -> list[dict[str, Any]]:
    return [
        {"id": "open_source", "name": "Open-source Project Plan", "description": "Governance, roadmap, contribution model, security and releases.", "icon": "</>"},
        {"id": "business", "name": "Business Plan", "description": "Customer problem, market, revenue, operations and finances.", "icon": "$"},
        {"id": "marketing", "name": "Marketing Plan", "description": "Audience, positioning, campaigns, channels and KPIs.", "icon": "↗"},
        {"id": "management", "name": "Management Plan", "description": "Roles, decisions, operating cadence, risks and resources.", "icon": "◎"},
        {"id": "blank", "name": "Blank Plan", "description": "Start from an empty document and build your own structure.", "icon": "+"},
    ]


def template_content(kind: str, title: str) -> str:
    safe_title = bleach.clean(clean_title(title), tags=[], strip=True)
    selected = clean_kind(kind)
    sections = {
        "open_source": f"""<h1>{safe_title}</h1><p><strong>Purpose:</strong> Describe the problem this open-source project solves and who benefits.</p><h2>1. Project Vision</h2><p>Define the long-term outcome and guiding principles.</p><h2>2. Scope and Non-goals</h2><p>Explain what belongs in the project and what does not.</p><h2>3. Users and Maintainers</h2><p>Identify users, maintainers, reviewers and decision owners.</p><h2>4. Architecture and Repository Structure</h2><p>Document components, interfaces, data flow and key folders.</p><h2>5. Contribution Workflow</h2><ul><li>Issue intake</li><li>Branch and pull-request policy</li><li>Review and merge requirements</li></ul><h2>6. Security and Trust</h2><p>Threat model, secret handling, dependency policy and disclosure process.</p><h2>7. Roadmap and Milestones</h2><p>List releases, measurable outcomes and target dates.</p><h2>8. Release and Support Policy</h2><p>Versioning, changelog, deprecation and support windows.</p><h2>9. Community and Governance</h2><p>Code of conduct, decision model, escalation and maintainer succession.</p><h2>10. Success Metrics</h2><p>Adoption, reliability, contributor health and user outcomes.</p>""",
        "business": f"""<h1>{safe_title}</h1><h2>Executive Summary</h2><p>Summarize the opportunity, product, customer and desired outcome.</p><h2>Customer Problem</h2><p>Describe the urgent problem and current alternatives.</p><h2>Solution and Value Proposition</h2><p>Explain why customers will choose this solution.</p><h2>Market and Competition</h2><p>Define segments, competitors and defensible advantage.</p><h2>Business Model</h2><p>Pricing, revenue, costs and unit economics.</p><h2>Operations Plan</h2><p>Delivery, technology, support and quality controls.</p><h2>Team and Management</h2><p>Roles, hiring and accountability.</p><h2>Financial Plan</h2><p>Forecast, funding and break-even targets.</p><h2>Risks and Milestones</h2><p>Owners, dates, evidence and mitigations.</p>""",
        "marketing": f"""<h1>{safe_title}</h1><h2>Marketing Objective</h2><p>State the measurable business outcome.</p><h2>Audience and Personas</h2><p>Segments, needs, triggers and objections.</p><h2>Positioning and Message</h2><p>Category, promise, proof and key messages.</p><h2>Channels</h2><ul><li>Owned</li><li>Earned</li><li>Paid</li><li>Community and partnerships</li></ul><h2>Campaign and Content Plan</h2><p>Offers, assets, owners, dates and publishing cadence.</p><h2>Budget and Measurement</h2><p>Allocation, funnel metrics, experiments and reporting.</p><h2>Risks and Response</h2><p>Brand, channel, data, timing and execution risks.</p>""",
        "management": f"""<h1>{safe_title}</h1><h2>Management Purpose</h2><p>Define outcomes, principles and boundaries.</p><h2>Organization and Roles</h2><p>Team structure, role charters and ownership.</p><h2>Decision Framework</h2><p>Decision rights, approvals, escalation and records.</p><h2>Operating Cadence</h2><p>Daily, weekly, monthly and quarterly reviews.</p><h2>Objectives and Measures</h2><p>Goals, key results and service levels.</p><h2>People and Resource Plan</h2><p>Hiring, development, budget, tools and capacity.</p><h2>Risk and Communication</h2><p>Risk register, stakeholders, reports and feedback loops.</p><h2>Continuous Improvement</h2><p>Retrospectives, lessons and policy updates.</p>""",
        "blank": f"<h1>{safe_title}</h1><p>Start writing your plan here.</p>",
    }
    return clean_html(sections[selected])


@dataclass(frozen=True, slots=True)
class AssistanceResult:
    action: str
    title: str
    html: str
    policy: dict[str, Any]
    provider: str


class PolicyDrivenAssistant:
    """Generate bounded planning help and optionally delegate to an Amosclaud model."""

    def __init__(self, *, endpoint: str | None = None, token: str | None = None, timeout_seconds: float = 20.0) -> None:
        self.endpoint = (endpoint or os.getenv("AMOSCLAUD_TEMPLATE_AI_ENDPOINT", "")).strip()
        self.token = token or os.getenv("AMOSCLAUD_TEMPLATE_AI_TOKEN", "")
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))

    def assist(self, *, action: str, plan: dict[str, Any], selection: str = "", instruction: str = "") -> AssistanceResult:
        normalized = str(action or "").strip().lower().replace("-", "_")
        if normalized not in ALLOWED_ACTIONS:
            raise TemplatePolicyError(f"Unsupported AI action: {normalized}")
        if len(instruction) > MAX_INSTRUCTION_LENGTH:
            raise TemplatePolicyError("AI instruction is too long")
        safe_plan = {
            "title": clean_title(str(plan.get("title", "Untitled plan"))),
            "kind": clean_kind(str(plan.get("kind", "blank"))),
            "status": clean_status(str(plan.get("status", "draft"))),
            "progress": clean_progress(plan.get("progress", 0)),
            "content": clean_html(str(plan.get("content", ""))),
        }
        safe_selection = clean_html(selection)[:30_000]
        policy = {
            "allowed_action": normalized,
            "write_mode": "suggest_only",
            "external_network": bool(self.endpoint),
            "content_limit": MAX_CONTENT_LENGTH,
            "secrets_allowed": False,
            "automatic_publish": False,
        }
        external = self._assist_external(normalized, safe_plan, safe_selection, instruction, policy) if self.endpoint else None
        if external:
            return external
        title, html = self._assist_local(normalized, safe_plan, safe_selection, instruction)
        return AssistanceResult(normalized, title, clean_html(html), policy, "policy-local")

    def _assist_external(self, action: str, plan: dict[str, Any], selection: str, instruction: str, policy: dict[str, Any]) -> AssistanceResult | None:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = httpx.post(self.endpoint, headers=headers, json={"task": "template_studio_assist", "action": action, "plan": plan, "selection": selection, "instruction": instruction, "policy": policy}, timeout=self.timeout_seconds)
            response.raise_for_status()
            if "application/json" not in response.headers.get("content-type", "").lower():
                return None
            data = response.json()
            html = clean_html(str(data.get("html", ""))) if isinstance(data, dict) else ""
            if not html:
                return None
            return AssistanceResult(action, clean_title(str(data.get("title", "Amosclaud suggestion"))), html, policy, "amosclaud-model-station")
        except (httpx.HTTPError, ValueError, TemplatePolicyError):
            return None

    def _assist_local(self, action: str, plan: dict[str, Any], selection: str, instruction: str) -> tuple[str, str]:
        text = bleach.clean(selection or plan["content"], tags=[], strip=True)
        short = " ".join(word for word in re.split(r"\s+", text) if word)[:900]
        guidance = {
            "outline": ("Suggested outline", "<h2>Suggested Outline</h2><ol><li>Purpose and desired outcome</li><li>Current situation and evidence</li><li>Scope, users and stakeholders</li><li>Strategy and workstreams</li><li>Milestones, owners and dates</li><li>Risks, policies and mitigations</li><li>Metrics and review cadence</li></ol>"),
            "improve": ("Improvement guidance", f"<h2>Improve this plan</h2><p>Focus on {bleach.clean(instruction, tags=[], strip=True) or 'clarity, ownership, evidence and measurable outcomes'}.</p><ul><li>Replace broad statements with measurable results.</li><li>Name an owner and review date for every commitment.</li><li>Separate assumptions from verified evidence.</li><li>Add acceptance criteria before execution.</li></ul><blockquote>{short}</blockquote>"),
            "summary": ("Executive summary", f"<h2>Executive Summary</h2><p>{short or 'The document does not contain enough text to summarize yet.'}</p><p><strong>Status:</strong> {plan['status'].title()} · <strong>Progress:</strong> {plan['progress']}%</p>"),
            "risks": ("Risk register starter", "<h2>Risk Register</h2><table><thead><tr><th>Risk</th><th>Signal</th><th>Owner</th><th>Response</th></tr></thead><tbody><tr><td>Scope expands without approval</td><td>Unplanned work enters the milestone</td><td>Plan owner</td><td>Require impact review</td></tr><tr><td>Decision or dependency is blocked</td><td>Owner or due date is missing</td><td>Workstream lead</td><td>Escalate at the operating review</td></tr><tr><td>Success cannot be verified</td><td>No measurable evidence</td><td>Quality owner</td><td>Add acceptance criteria</td></tr></tbody></table>"),
            "milestones": ("Milestone plan", "<h2>Milestones</h2><ol><li><strong>Discover:</strong> validate users and constraints.</li><li><strong>Design:</strong> approve scope and policy.</li><li><strong>Build:</strong> deliver the smallest usable version.</li><li><strong>Verify:</strong> test acceptance criteria.</li><li><strong>Launch:</strong> publish and monitor.</li><li><strong>Improve:</strong> review metrics and lessons.</li></ol>"),
            "open_source": ("Open-source policy pack", "<h2>Open-source Policy Pack</h2><ul><li>Choose and document a license.</li><li>Add CONTRIBUTING and CODE_OF_CONDUCT.</li><li>Define issue, pull-request and maintainer workflows.</li><li>Publish SECURITY and supported-version policies.</li><li>Automate tests, releases and dependency checks.</li><li>Track contributor onboarding and review time.</li></ul>"),
            "business": ("Business-plan controls", "<h2>Business-plan Controls</h2><ul><li>Identify the paying customer and urgent problem.</li><li>Test pricing and willingness to pay.</li><li>Track acquisition cost, margin, retention and runway.</li><li>Assign sales, delivery, support and finance owners.</li><li>Define decision thresholds for spending and hiring.</li></ul>"),
            "marketing": ("Marketing-plan controls", "<h2>Marketing-plan Controls</h2><ul><li>Connect every campaign to one audience and outcome.</li><li>Define message, proof, offer, channel, owner and budget.</li><li>Measure qualified demand, conversion and retention.</li><li>Review experiments weekly and stop weak channels.</li></ul>"),
            "management": ("Management-plan controls", "<h2>Management-plan Controls</h2><ul><li>Document decision rights and escalation levels.</li><li>Give every objective an owner, measure and review date.</li><li>Maintain a visible risk and dependency register.</li><li>Use weekly operating and monthly outcome reviews.</li><li>Record decisions and update policies from verified lessons.</li></ul>"),
        }
        return guidance[action]
