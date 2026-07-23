(() => {
  "use strict";

  const engineRepository = "wamakologeorge-dev/amosclaude-clean";
  const commandRepository = "wamakologeorge-dev/Amosclaud1";
  const byId = (id) => document.getElementById(id);

  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
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
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch {
      throw new Error("GitHub returned invalid JSON");
    }
  }

  function statusTone(status) {
    const value = String(status || "unknown").toLowerCase();
    if (["pass", "passed", "success", "verified", "healthy", "completed"].includes(value)) return "success";
    if (["fail", "failed", "failure", "critical", "blocked", "rolled_back", "cancelled", "timed_out"].includes(value)) return "failure";
    if (["running", "in_progress", "reviewing", "queued", "waiting"].includes(value)) return "running";
    return "queued";
  }

  function extractField(text, labels) {
    for (const label of labels) {
      const expression = new RegExp(`(?:^|\\n)[-*# >]*\\*?\\*?${label}\\*?\\*?\\s*:\\s*\\`?([^\\n\\`]+)`, "i");
      const match = text.match(expression);
      if (match) return match[1].trim();
    }
    return "";
  }

  function parseRepairComment(comment, issue) {
    const text = String(comment.body || "");
    const relevant = /Amosclaud/i.test(text) && /(repair result|autonomous repair report|live execution|Doctor evidence|final result|verdict|status)/i.test(text);
    if (!relevant) return null;

    const verdict = extractField(text, ["Result", "Final result", "Final verdict", "Verdict", "Status"])
      .replace(/[^A-Za-z_ -].*$/, "")
      .trim()
      .toUpperCase() || (/VERIFICATION FAILED|FINAL RESULT:\s*FAIL/i.test(text) ? "FAIL" : /PASS|VERIFIED|SUCCESS/i.test(text) ? "PASS" : "UPDATE");
    const target = extractField(text, ["Target", "Repository"]) || engineRepository;
    const request = extractField(text, ["Request", "Objective"]) || `Issue #${issue.number}`;
    const stage = extractField(text, ["Stage", "Current stage"]) || (/Doctor/i.test(text) ? "VERIFY" : /repair/i.test(text) ? "REPAIR" : "PROCESSING");
    const published = extractField(text, ["Repository changes published", "Pull request", "Publication"]) || (/published:\s*no/i.test(text) ? "No" : /pull request|commit/i.test(text) ? "Recorded in evidence" : "Not reported");
    const changedFiles = extractField(text, ["Changed files"]) || "See evidence";

    return {
      kind: "repair",
      title: issue.title,
      issueNumber: issue.number,
      verdict,
      target,
      request,
      stage,
      published,
      changedFiles,
      updatedAt: comment.updated_at || comment.created_at,
      url: comment.html_url || issue.html_url,
      source: "Amosclaud1 issue evidence",
    };
  }

  function parseRun(run) {
    const fixerLike = /amosclaud|fixer|repair|doctor|autonomous/i.test(`${run.name || ""} ${run.display_title || ""}`);
    if (!fixerLike) return null;
    return {
      kind: "workflow",
      title: run.name || "GitHub Actions run",
      verdict: String(run.conclusion || run.status || "unknown").toUpperCase(),
      target: engineRepository,
      request: run.display_title || `${run.event || "event"} on ${run.head_branch || "default branch"}`,
      stage: run.status === "completed" ? "COMPLETED" : String(run.status || "RUNNING").toUpperCase(),
      published: run.head_sha ? `Commit ${String(run.head_sha).slice(0, 7)}` : "Not reported",
      changedFiles: "Workflow evidence",
      updatedAt: run.updated_at || run.created_at,
      url: run.html_url,
      source: "GitHub Actions evidence",
    };
  }

  function relativeTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Unknown time";
    const minutes = Math.round((date.getTime() - Date.now()) / 60000);
    if (Math.abs(minutes) < 60) return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(minutes, "minute");
    const hours = Math.round(minutes / 60);
    if (Math.abs(hours) < 24) return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(hours, "hour");
    return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(Math.round(hours / 24), "day");
  }

  function renderMirrorCard(record) {
    const card = node("article", `fixer-mirror-card ${statusTone(record.verdict)}`);
    const top = node("div", "fixer-mirror-top");
    const identity = node("div");
    identity.append(node("small", "fixer-source", record.source), node("h3", "", record.title));
    const verdict = node("span", `fixer-verdict ${statusTone(record.verdict)}`, record.verdict);
    top.append(identity, verdict);

    const path = node("ol", "fixer-stage-path");
    ["ANALYZE", "PLAN", "EDIT", "TEST", "VERIFY", "PUBLISH"].forEach((stage) => {
      path.append(node("li", stage === record.stage ? "current" : "", stage));
    });

    const facts = node("dl", "fixer-facts");
    [
      ["Target", record.target],
      ["Request", record.request],
      ["Current evidence", record.stage],
      ["Publication", record.published],
      ["Changed files", record.changedFiles],
      ["Updated", relativeTime(record.updatedAt)],
    ].forEach(([label, value]) => {
      const group = node("div");
      group.append(node("dt", "", label), node("dd", "", value));
      facts.append(group);
    });

    const link = node("a", "button button-small button-secondary", "Open first-party evidence");
    link.href = record.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    card.append(top, path, facts, link);
    return card;
  }

  async function loadIssueEvidence() {
    const issues = await githubJson(`https://api.github.com/repos/${commandRepository}/issues?state=all&sort=updated&direction=desc&per_page=8`);
    const issueRecords = issues.filter((item) => !item.pull_request).slice(0, 6);
    const commentGroups = await Promise.all(issueRecords.map(async (issue) => {
      try {
        const comments = await githubJson(`https://api.github.com/repos/${commandRepository}/issues/${issue.number}/comments?per_page=100`);
        return comments.map((comment) => parseRepairComment(comment, issue)).filter(Boolean);
      } catch {
        return [];
      }
    }));
    return commentGroups.flat();
  }

  async function loadWorkflowEvidence() {
    const payload = await githubJson(`https://api.github.com/repos/${engineRepository}/actions/runs?per_page=20`);
    return (payload.workflow_runs || []).map(parseRun).filter(Boolean);
  }

  async function loadPublicMirror() {
    const list = byId("fixer-mirror-list");
    const status = byId("fixer-mirror-status");
    if (!list || !status) return;
    list.replaceChildren(node("p", "loading", "Loading true public Amosclaud processing evidence…"));
    status.textContent = "Reading Amosclaud1 issues and GitHub Actions";
    try {
      const [issueEvidence, workflowEvidence] = await Promise.all([loadIssueEvidence(), loadWorkflowEvidence()]);
      const records = [...issueEvidence, ...workflowEvidence]
        .sort((left, right) => new Date(right.updatedAt || 0) - new Date(left.updatedAt || 0))
        .slice(0, 8);
      list.replaceChildren();
      records.forEach((record) => list.append(renderMirrorCard(record)));
      if (!records.length) list.append(node("p", "loading", "No public Fixer processing records were returned by GitHub."));
      status.textContent = `${records.length} public evidence records · refreshed ${new Date().toLocaleTimeString()}`;
    } catch (error) {
      list.replaceChildren(node("p", "loading", `Public Fixer mirror unavailable: ${error.message}`));
      status.textContent = "GitHub evidence could not be loaded";
    }
  }

  function createPublicMirror() {
    const main = document.querySelector("main");
    const hero = document.querySelector(".hero");
    if (!main || !hero || byId("public-fixer-mirror")) return;

    const section = node("section", "public-fixer-mirror");
    section.id = "public-fixer-mirror";
    const heading = node("div", "section-heading-row");
    const copy = node("div");
    copy.append(
      node("p", "eyebrow", "Public Fixer mirror"),
      node("h2", "", "Watch Amosclaud process real GitHub work."),
      node("p", "section-copy", "These cards mirror public issue reports and GitHub Actions evidence. They show failures, approvals, verification, publication, and rollback exactly as GitHub reports them."),
    );
    const controls = node("div", "fixer-mirror-controls");
    const status = node("span", "fixer-mirror-status", "Waiting for GitHub evidence");
    status.id = "fixer-mirror-status";
    const refresh = node("button", "button button-small button-secondary", "Refresh public results");
    refresh.type = "button";
    refresh.addEventListener("click", loadPublicMirror);
    controls.append(status, refresh);
    heading.append(copy, controls);

    const truth = node("p", "fixer-mirror-truth", "No result is manufactured by the landing page. Every displayed record links back to the public GitHub evidence that produced it.");
    const list = node("div", "fixer-mirror-list");
    list.id = "fixer-mirror-list";
    section.append(heading, truth, list);
    hero.after(section);
    loadPublicMirror();
  }

  createPublicMirror();
})();
