(() => {
  "use strict";

  const ENGINE_REPOSITORY = "wamakologeorge-dev/amosclaude-clean";
  const COMMAND_REPOSITORY = "wamakologeorge-dev/Amosclaud1";
  const CONTROL_API = String(window.AMOSCLAUD_CONTROL_API || "").replace(/\/$/, "");
  const byId = (id) => document.getElementById(id);

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function githubJson(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/vnd.github+json" },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.toLowerCase().includes("application/json")) {
      throw new Error("GitHub returned a non-JSON response");
    }
    return response.json();
  }

  function latestRunsOnly(runs) {
    const latest = new Map();
    for (const run of runs) {
      const key = `${run.workflow_id || run.name}:${run.head_branch || ""}:${run.event || ""}`;
      const previous = latest.get(key);
      const currentTime = new Date(run.updated_at || run.created_at || 0).getTime();
      const previousTime = previous ? new Date(previous.updated_at || previous.created_at || 0).getTime() : -1;
      if (!previous || currentTime > previousTime) latest.set(key, run);
    }
    return [...latest.values()];
  }

  function riskFor(record) {
    const text = `${record.title} ${record.detail}`.toLowerCase();
    if (/workflow|permission|secret|token|deploy|production/.test(text)) return "HIGH";
    if (/test|repair|fix|failure|critical/.test(text)) return "MEDIUM";
    return "LOW";
  }

  function issueRecord(issue, repository) {
    const title = String(issue.title || "Autonomous approval required");
    if (!/approval required|amosclaud approval|autonomous approval/i.test(title)) return null;
    return {
      sourceType: "approval",
      sourceId: `issue:${repository}:${issue.number}`,
      repository,
      title,
      detail: String(issue.body || "A trusted decision is required before Amosclaud continues.").slice(0, 500),
      status: "WAITING",
      stage: "APPROVAL",
      evidenceUrl: issue.html_url,
      createdAt: issue.created_at,
      updatedAt: issue.updated_at,
      action: "Authorize the proposed governed operation once, or deny it without publishing changes.",
    };
  }

  function runRecord(run) {
    if (!["failure", "timed_out", "cancelled", "action_required"].includes(run.conclusion)) return null;
    return {
      sourceType: "workflow",
      sourceId: `run:${run.id}`,
      repository: ENGINE_REPOSITORY,
      title: `${run.name || "GitHub workflow"} failed`,
      detail: `${run.display_title || run.event || "Workflow execution"} on ${run.head_branch || "default branch"}`,
      status: "NEEDS ACTION",
      stage: "TEST",
      evidenceUrl: run.html_url,
      createdAt: run.created_at,
      updatedAt: run.updated_at,
      action: "Allow Amosclaud Autonomous to inspect the failure and prepare a verified repair, or deny the action.",
    };
  }

  function formatNumber(index) {
    return `#${String(index + 1).padStart(3, "0")}`;
  }

  function decisionPayload(record, decision) {
    return {
      approval_id: record.sourceId,
      decision,
      repository: record.repository,
      source_type: record.sourceType,
      evidence_url: record.evidenceUrl,
      single_use: true,
    };
  }

  function showDecisionMessage(card, text, tone) {
    const status = card.querySelector(".approval-decision-status");
    status.textContent = text;
    status.dataset.tone = tone;
  }

  async function submitDecision(card, record, decision) {
    const buttons = card.querySelectorAll("button[data-decision]");
    buttons.forEach((button) => { button.disabled = true; });

    if (!CONTROL_API) {
      showDecisionMessage(
        card,
        decision === "approve"
          ? "APPROVED was not recorded. Connect the secure Amosclaud Control API to make website decisions authoritative."
          : "DENIED was not recorded. Connect the secure Amosclaud Control API to make website decisions authoritative.",
        "blocked",
      );
      buttons.forEach((button) => { button.disabled = false; });
      return;
    }

    try {
      const response = await fetch(`${CONTROL_API}/api/v1/approvals/decision`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(decisionPayload(record, decision)),
      });
      const contentType = response.headers.get("content-type") || "";
      if (!response.ok || !contentType.toLowerCase().includes("application/json")) {
        throw new Error(`Control API rejected the decision (${response.status})`);
      }
      const result = await response.json();
      if (!result || result.recorded !== true) throw new Error("The decision was not confirmed");
      card.dataset.state = decision === "approve" ? "approved" : "denied";
      showDecisionMessage(
        card,
        decision === "approve"
          ? "APPROVED ONCE — Amosclaud may continue this exact operation."
          : "DENIED — Amosclaud must stop and publish no repository changes.",
        decision,
      );
    } catch (error) {
      showDecisionMessage(card, `Decision failed: ${error.message}`, "failure");
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function renderCard(record, index) {
    const card = element("article", "autonomous-approval-card");
    card.dataset.state = "waiting";

    const header = element("div", "approval-card-header");
    const identity = element("div");
    identity.append(
      element("span", "approval-number", formatNumber(index)),
      element("h3", "", record.title),
      element("small", "", record.repository),
    );
    const state = element("span", "approval-state", record.status);
    header.append(identity, state);

    const facts = element("dl", "approval-facts");
    [
      ["Stage", record.stage],
      ["Risk", riskFor(record)],
      ["Error / evidence", record.detail],
      ["Proposed action", record.action],
      ["Decision scope", "Single-use for this exact record"],
    ].forEach(([label, value]) => {
      const group = element("div");
      group.append(element("dt", "", label), element("dd", "", value));
      facts.append(group);
    });

    const controls = element("div", "approval-controls");
    const approve = element("button", "button approval-approve", "Approve once");
    approve.type = "button";
    approve.dataset.decision = "approve";
    const deny = element("button", "button button-secondary approval-deny", "Deny");
    deny.type = "button";
    deny.dataset.decision = "deny";
    const evidence = element("a", "text-link", "Review evidence ↗");
    evidence.href = record.evidenceUrl;
    evidence.target = "_blank";
    evidence.rel = "noreferrer";
    controls.append(approve, deny, evidence);

    const decisionStatus = element("p", "approval-decision-status", CONTROL_API
      ? "Waiting for a trusted website decision."
      : "Display-only mode: secure Control API connection is required to record Approve or Deny.");
    decisionStatus.setAttribute("role", "status");

    approve.addEventListener("click", () => submitDecision(card, record, "approve"));
    deny.addEventListener("click", () => submitDecision(card, record, "deny"));
    card.append(header, facts, controls, decisionStatus);
    return card;
  }

  async function loadQueue() {
    const list = byId("autonomous-approval-list");
    const summary = byId("autonomous-approval-summary");
    if (!list || !summary) return;
    list.replaceChildren(element("p", "loading", "Loading ordered Autonomous actions…"));
    summary.textContent = "Reading public GitHub errors and approval records";

    try {
      const [engineIssues, commandIssues, runPayload] = await Promise.all([
        githubJson(`https://api.github.com/repos/${ENGINE_REPOSITORY}/issues?state=open&per_page=50`),
        githubJson(`https://api.github.com/repos/${COMMAND_REPOSITORY}/issues?state=open&per_page=50`),
        githubJson(`https://api.github.com/repos/${ENGINE_REPOSITORY}/actions/runs?per_page=40`),
      ]);

      const approvalRecords = [
        ...engineIssues.filter((item) => !item.pull_request).map((item) => issueRecord(item, ENGINE_REPOSITORY)),
        ...commandIssues.filter((item) => !item.pull_request).map((item) => issueRecord(item, COMMAND_REPOSITORY)),
      ].filter(Boolean);
      const failureRecords = latestRunsOnly(runPayload.workflow_runs || []).map(runRecord).filter(Boolean);
      const records = [...approvalRecords, ...failureRecords]
        .sort((left, right) => new Date(left.createdAt || 0) - new Date(right.createdAt || 0));

      list.replaceChildren();
      records.forEach((record, index) => list.append(renderCard(record, index)));
      if (!records.length) list.append(element("p", "approval-empty", "No current failures or approvals require action."));
      summary.textContent = `${records.length} ordered action${records.length === 1 ? "" : "s"} · oldest first`;
    } catch (error) {
      list.replaceChildren(element("p", "approval-empty", `Approval queue unavailable: ${error.message}`));
      summary.textContent = "GitHub evidence could not be loaded";
    }
  }

  function createQueue() {
    const main = document.querySelector("main");
    const reviewCenter = byId("review-center");
    if (!main || byId("autonomous-approval-queue")) return;

    const section = element("section", "autonomous-approval-queue");
    section.id = "autonomous-approval-queue";
    const heading = element("div", "section-heading-row");
    const copy = element("div");
    copy.append(
      element("p", "eyebrow", "Autonomous approval queue"),
      element("h2", "", "Review every error in order, then approve or deny."),
      element("p", "section-copy", "Each numbered card maps to real GitHub evidence. Approvals are single-use and must never authorize a different operation."),
    );
    const controls = element("div", "approval-heading-controls");
    const summary = element("span", "approval-summary", "Waiting for GitHub evidence");
    summary.id = "autonomous-approval-summary";
    const refresh = element("button", "button button-small button-secondary", "Refresh queue");
    refresh.type = "button";
    refresh.addEventListener("click", loadQueue);
    controls.append(summary, refresh);
    heading.append(copy, controls);

    const connection = element(
      "p",
      "approval-connection-note",
      CONTROL_API
        ? "Secure website decision connection detected. GitHub remains the audit source of truth."
        : "The queue is live and truthful. Approve/Deny becomes authoritative after the secure Amosclaud Control API is connected; no token is stored in this page.",
    );
    const list = element("div", "autonomous-approval-list");
    list.id = "autonomous-approval-list";
    section.append(heading, connection, list);
    if (reviewCenter) reviewCenter.after(section); else main.prepend(section);
    loadQueue();
  }

  createQueue();
})();
