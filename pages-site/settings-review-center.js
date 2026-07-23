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

  function toneFor(value) {
    const status = String(value || "unknown").toLowerCase();
    if (["success", "completed", "pass", "verified", "closed"].includes(status)) return "success";
    if (["failure", "failed", "timed_out", "cancelled", "blocked", "critical"].includes(status)) return "failure";
    if (["in_progress", "running", "queued", "waiting"].includes(status)) return "running";
    return "queued";
  }

  function createSettings() {
    const button = node("button", "settings-button", "⚙");
    button.type = "button";
    button.setAttribute("aria-label", "Open Amosclaud settings");
    button.setAttribute("aria-expanded", "false");

    const backdrop = node("div", "settings-backdrop");
    backdrop.hidden = true;
    const drawer = node("aside", "settings-drawer");
    drawer.hidden = true;
    drawer.setAttribute("aria-label", "Amosclaud settings");

    const header = node("div", "settings-drawer-header");
    const title = node("div");
    title.append(node("p", "eyebrow", "Settings"), node("h2", "", "Amosclaud control settings"));
    const close = node("button", "settings-close", "×");
    close.type = "button";
    close.setAttribute("aria-label", "Close settings");
    header.append(title, close);

    const truth = node("section", "settings-section");
    truth.append(node("h3", "", "Truth and evidence"));
    [
      ["Success reporting", "Only after GitHub checks or Doctor evidence"],
      ["Unknown results", "Never displayed as PASS"],
      ["Sensitive work", "Requires auditable approval"],
      ["Browser credentials", "No GitHub token stored"],
    ].forEach(([label, value]) => {
      const row = node("div", "settings-row");
      row.append(node("strong", "", label), node("span", "", value));
      truth.append(row);
    });

    const routing = node("section", "settings-section");
    routing.append(node("h3", "", "Command routing"));
    [
      ["Command bridge", commandRepository],
      ["Execution engine", engineRepository],
      ["Repair agent", "Amosclaud Fixer"],
      ["Verification authority", "Doctor + GitHub checks"],
    ].forEach(([label, value]) => {
      const row = node("div", "settings-row");
      row.append(node("strong", "", label), node("span", "", value));
      routing.append(row);
    });

    const capability = node("section", "settings-section");
    capability.append(
      node("h3", "", "Current website capability"),
      node("p", "section-copy", "Public GitHub data, command preparation, review evidence, and approval visibility work from this static site. Direct private-repository writes and real-time Socket.IO require the secure GitHub App backend phase."),
    );
    drawer.append(header, truth, routing, capability);
    document.body.append(button, backdrop, drawer);

    const open = () => {
      drawer.hidden = false;
      backdrop.hidden = false;
      button.setAttribute("aria-expanded", "true");
      close.focus();
    };
    const shut = () => {
      drawer.hidden = true;
      backdrop.hidden = true;
      button.setAttribute("aria-expanded", "false");
      button.focus();
    };
    button.addEventListener("click", open);
    close.addEventListener("click", shut);
    backdrop.addEventListener("click", shut);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !drawer.hidden) shut();
    });
  }

  function addReviewEntry(list, title, detail, status, url) {
    const card = node("article", `review-entry ${toneFor(status)}`);
    card.append(node("strong", "", title), node("small", "", detail));
    if (url) {
      const link = node("a", "text-link", "Open evidence ↗");
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      card.append(link);
    }
    list.append(card);
  }

  function setSummary(id, value, detail) {
    const card = byId(id);
    if (!card) return;
    card.querySelector("strong").textContent = String(value);
    card.querySelector("span").textContent = detail;
  }

  function latestRunsOnly(runs) {
    const latest = new Map();
    runs.forEach((run) => {
      const key = `${run.workflow_id || run.name}:${run.head_branch || "default"}`;
      if (!latest.has(key)) latest.set(key, run);
    });
    return [...latest.values()];
  }

  async function loadReviewData() {
    const list = byId("review-feed-list");
    if (!list) return;
    list.replaceChildren(node("p", "review-empty", "Loading verified GitHub evidence…"));
    try {
      const [runsPayload, issues, pulls] = await Promise.all([
        githubJson(`https://api.github.com/repos/${engineRepository}/actions/runs?per_page=12`),
        githubJson(`https://api.github.com/repos/${engineRepository}/issues?state=open&per_page=30`),
        githubJson(`https://api.github.com/repos/${engineRepository}/pulls?state=open&per_page=20`),
      ]);
      const rawRuns = Array.isArray(runsPayload.workflow_runs) ? runsPayload.workflow_runs : [];
      const runs = latestRunsOnly(rawRuns);
      const approvalIssues = issues.filter((item) => !item.pull_request && /approval required|amosclaud approval/i.test(item.title || ""));
      const failedRuns = runs.filter((run) => ["failure", "timed_out", "cancelled"].includes(run.conclusion));
      const successfulRuns = runs.filter((run) => run.conclusion === "success");
      const activeRuns = runs.filter((run) => run.status !== "completed");

      setSummary("review-fixed", successfulRuns.length, "Recent checks completed successfully");
      setSummary("review-needs-action", failedRuns.length + approvalIssues.length, "Current failures or approvals need attention");
      setSummary("review-active", activeRuns.length, "Checks currently queued or running");

      list.replaceChildren();
      activeRuns.slice(0, 4).forEach((run) => addReviewEntry(list, `${run.name} · RUNNING`, `${run.event} on ${run.head_branch || "default branch"}`, run.status, run.html_url));
      failedRuns.slice(0, 6).forEach((run) => addReviewEntry(list, `${run.name} · ${String(run.conclusion).toUpperCase()}`, "GitHub check requires diagnosis or repair.", run.conclusion, run.html_url));
      approvalIssues.slice(0, 5).forEach((issue) => addReviewEntry(list, issue.title, `Approval record #${issue.number} requires a trusted decision.`, "waiting", issue.html_url));
      successfulRuns.slice(0, 5).forEach((run) => addReviewEntry(list, `${run.name} · VERIFIED`, "GitHub returned a successful completed check.", "success", run.html_url));
      pulls.slice(0, 4).forEach((pull) => addReviewEntry(list, `PR #${pull.number} · ${pull.title}`, `${pull.head.ref} → ${pull.base.ref}`, "queued", pull.html_url));
      if (!list.children.length) list.append(node("p", "review-empty", "GitHub returned no recent review records."));
    } catch (error) {
      list.replaceChildren(node("p", "review-empty", `Review data unavailable: ${error.message}`));
      setSummary("review-fixed", "—", "Unable to load GitHub checks");
      setSummary("review-needs-action", "—", "Unable to load required actions");
      setSummary("review-active", "—", "Unable to load active checks");
    }
  }

  function detectCommand(message) {
    const value = message.toLowerCase();
    if (/\b(?:fix|repair|resolve)\b/.test(value)) return "fix";
    if (/\b(?:verify|check|prove)\b/.test(value)) return "verify";
    if (/\b(?:health|status)\b/.test(value)) return "health";
    if (/\bmission\b/.test(value)) return "mission";
    if (/\b(?:goal|plan|planning)\b/.test(value)) return "goal";
    if (/\b(?:triage|priority)\b/.test(value)) return "triage";
    return "inspect";
  }

  function prepareCommandFromChat(message) {
    const action = detectCommand(message);
    const type = byId("request-type");
    const title = byId("request-title");
    const body = byId("request-body");
    if (type) type.value = action;
    if (title) title.value = `${action[0].toUpperCase()} request from website chat`;
    if (body) body.value = `Target repository: ${engineRepository}\n\nWebsite chat request:\n${message}`;
    [type, title, body].filter(Boolean).forEach((field) => field.dispatchEvent(new Event("input", { bubbles: true })));
    return action;
  }

  function addChatMessage(log, role, text) {
    const message = node("div", `chat-message ${role}`, text);
    log.append(message);
    log.scrollTop = log.scrollHeight;
  }

  function createReviewCenter() {
    const main = document.querySelector("main");
    const control = byId("control-plane");
    if (!main || byId("review-center")) return;

    const section = node("section", "review-center");
    section.id = "review-center";
    const heading = node("div", "section-heading-row");
    const copy = node("div");
    copy.append(node("p", "eyebrow", "True review center"), node("h2", "", "What Amosclaud fixed, checked, and still needs."), node("p", "section-copy", "This dashboard reports GitHub evidence. It does not convert missing evidence into success."));
    const refresh = node("button", "button button-small button-secondary", "Refresh reviews");
    refresh.type = "button";
    refresh.addEventListener("click", loadReviewData);
    heading.append(copy, refresh);

    const summary = node("div", "review-summary");
    [["review-fixed", "—", "Loading successful checks"], ["review-needs-action", "—", "Loading required actions"], ["review-active", "—", "Loading active checks"]].forEach(([id, value, detail]) => {
      const card = node("article");
      card.id = id;
      card.append(node("strong", "", value), node("span", "", detail));
      summary.append(card);
    });

    const grid = node("div", "review-grid");
    const feed = node("section", "review-feed");
    feed.append(node("h3", "", "GitHub reviews and evidence"));
    const list = node("div", "review-feed-list");
    list.id = "review-feed-list";
    feed.append(list);

    const chat = node("section", "website-chat");
    chat.append(node("h3", "", "Chat with Amosclaud Bot"));
    const log = node("div", "chat-log");
    log.id = "website-chat-log";
    addChatMessage(log, "bot", "Tell me what to inspect, verify, fix, or plan. I will prepare one auditable command card. Direct execution remains permission-gated through Amosclaud1 and GitHub Actions.");
    const form = node("form", "chat-form");
    const input = node("textarea");
    input.id = "website-chat-input";
    input.rows = 5;
    input.required = true;
    input.maxLength = 2000;
    input.placeholder = "Example: Fix the failing Pages workflow and verify all checks.";
    const send = node("button", "button", "Prepare Amosclaud command");
    send.type = "submit";
    form.append(input, send);
    const truth = node("p", "truth-note", "This static version prepares the command and moves it to the existing governed command form. It does not silently write to GitHub or claim that work has started.");
    chat.append(log, form, truth);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      addChatMessage(log, "user", text);
      const action = prepareCommandFromChat(text);
      addChatMessage(log, "bot", `Prepared a ${action.toUpperCase()} command card. Review the generated command and trusted-role requirement below before sending it through Amosclaud1.`);
      input.value = "";
      byId("submit")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    grid.append(feed, chat);
    section.append(heading, summary, grid);
    if (control) control.after(section); else main.prepend(section);
    loadReviewData();
  }

  createSettings();
  createReviewCenter();
})();
