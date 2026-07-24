(() => {
  "use strict";

  const repositories = [
    {
      fullName: "wamakologeorge-dev/amosclaude-clean",
      label: "Amosclaud Engine",
      description: "Autonomous brain, Bot, Doctor, Fixer, workflows, and verified execution.",
    },
    {
      fullName: "wamakologeorge-dev/Amosclaud1",
      label: "Amosclaud Command Hub",
      description: "Public command records, progress events, approvals, and final evidence.",
    },
  ];

  const state = {
    selectedRepository: repositories[0].fullName,
    repositories: new Map(),
  };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function githubJson(url) {
    const response = await fetch(url, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.toLowerCase().includes("application/json")) {
      throw new Error("GitHub returned a non-JSON response");
    }
    return response.json();
  }

  function formatTime(value) {
    if (!value) return "Unknown time";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Unknown time";
    return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
      Math.round((date.getTime() - Date.now()) / 60000),
      "minute",
    );
  }

  function workflowTone(conclusion, status) {
    if (status !== "completed") return "running";
    if (conclusion === "success") return "success";
    if (["failure", "timed_out", "cancelled"].includes(conclusion)) return "failure";
    return "queued";
  }

  function statusPill(label, tone = "queued") {
    const pill = element("span", `control-pill ${tone}`, label);
    return pill;
  }

  function buildPanel(title, subtitle) {
    const panel = element("section", "control-panel");
    const heading = element("div", "control-panel-heading");
    const copy = element("div");
    copy.append(element("p", "eyebrow", "Website control plane"), element("h2", "", title));
    if (subtitle) copy.append(element("p", "section-copy", subtitle));
    heading.append(copy);
    panel.append(heading);
    return panel;
  }

  function commandFor(target, action) {
    const requestType = document.getElementById("request-type");
    const requestTitle = document.getElementById("request-title");
    const requestBody = document.getElementById("request-body");
    if (requestType) requestType.value = action;
    if (requestTitle) requestTitle.value = `${action[0].toUpperCase()}${action.slice(1)} ${target}`;
    if (requestBody) requestBody.value = `Target repository: ${target}\n\nDescribe the objective, expected result, and available evidence here.`;
    [requestType, requestTitle, requestBody].filter(Boolean).forEach((field) => {
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    document.getElementById("submit")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderRepositoryCards(container) {
    container.replaceChildren();
    repositories.forEach((repository) => {
      const data = state.repositories.get(repository.fullName);
      const card = element("article", "project-card");
      card.tabIndex = 0;
      card.setAttribute("role", "button");
      card.setAttribute("aria-label", `Open ${repository.label} workspace`);

      const top = element("div", "project-card-top");
      const identity = element("div");
      identity.append(element("span", "project-kicker", repository.fullName), element("h3", "", repository.label));
      top.append(identity, statusPill(data?.workflowLabel || "Loading", data?.workflowTone || "queued"));

      const metrics = element("div", "project-metrics");
      [
        ["Issues", data?.openIssues ?? "—"],
        ["Pull requests", data?.openPulls ?? "—"],
        ["Default branch", data?.defaultBranch || "—"],
      ].forEach(([label, value]) => {
        const metric = element("span");
        metric.append(element("strong", "", String(value)), element("small", "", label));
        metrics.append(metric);
      });

      const actions = element("div", "project-actions");
      ["inspect", "health", "verify", "fix"].forEach((action) => {
        const button = element("button", action === "fix" ? "button button-small button-secondary" : "button button-small", action);
        button.type = "button";
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          commandFor(repository.fullName, action);
        });
        actions.append(button);
      });

      card.append(top, element("p", "project-description", repository.description), metrics, actions);
      const open = () => {
        state.selectedRepository = repository.fullName;
        renderWorkspace();
        document.getElementById("workspace")?.scrollIntoView({ behavior: "smooth", block: "start" });
      };
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
      container.append(card);
    });
  }

  function itemCard(item, kind) {
    const card = element("article", "workspace-item");
    const header = element("div", "workspace-item-header");
    header.append(
      element("strong", "", `#${item.number} ${item.title}`),
      statusPill(String(item.state || "open").toUpperCase(), item.state === "open" ? "success" : "queued"),
    );
    const details = element("p", "", kind === "pull"
      ? `${item.head?.ref || "branch"} → ${item.base?.ref || "main"} · ${item.user?.login || "GitHub user"}`
      : `${item.comments || 0} comments · ${item.user?.login || "GitHub user"}`);
    const footer = element("div", "workspace-item-footer");
    footer.append(element("small", "", formatTime(item.updated_at || item.created_at)));
    const source = element("a", "text-link", "GitHub record ↗");
    source.href = item.html_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    footer.append(source);
    card.append(header, details, footer);
    return card;
  }

  function workflowCard(run) {
    const tone = workflowTone(run.conclusion, run.status);
    const card = element("article", "workspace-item");
    const header = element("div", "workspace-item-header");
    header.append(element("strong", "", run.name), statusPill((run.conclusion || run.status || "unknown").toUpperCase(), tone));
    card.append(header, element("p", "", `${run.event || "event"} · ${run.head_branch || "default branch"}`));
    const footer = element("div", "workspace-item-footer");
    footer.append(element("small", "", formatTime(run.updated_at || run.created_at)));
    const source = element("a", "text-link", "Run evidence ↗");
    source.href = run.html_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    footer.append(source);
    card.append(footer);
    return card;
  }

  function approvalCard(issue) {
    const card = element("article", "workspace-item approval-item");
    const header = element("div", "workspace-item-header");
    header.append(element("strong", "", issue.title), statusPill(issue.state === "open" ? "WAITING" : "RECORDED", issue.state === "open" ? "running" : "success"));
    card.append(header, element("p", "", "Sensitive action governed by Amosclaud’s auditable, single-use approval policy."));
    const footer = element("div", "workspace-item-footer");
    footer.append(element("small", "", `Issue #${issue.number}`));
    const source = element("a", "text-link", "Review approval ↗");
    source.href = issue.html_url;
    source.target = "_blank";
    source.rel = "noreferrer";
    footer.append(source);
    card.append(footer);
    return card;
  }

  function renderColumn(title, items, renderer, emptyText) {
    const column = element("section", "workspace-column");
    column.append(element("h3", "", title));
    const list = element("div", "workspace-list");
    if (!items?.length) list.append(element("p", "loading", emptyText));
    else items.slice(0, 5).forEach((item) => list.append(renderer(item)));
    column.append(list);
    return column;
  }

  function renderWorkspace() {
    const host = document.getElementById("workspace-grid");
    const title = document.getElementById("workspace-title");
    if (!host || !title) return;
    const data = state.repositories.get(state.selectedRepository);
    title.textContent = state.selectedRepository;
    host.replaceChildren();
    if (!data) {
      host.append(element("p", "loading", "Loading repository workspace…"));
      return;
    }
    host.append(
      renderColumn("Issues", data.issues, (item) => itemCard(item, "issue"), "No open issues."),
      renderColumn("Pull requests", data.pulls, (item) => itemCard(item, "pull"), "No open pull requests."),
      renderColumn("Workflow runs", data.runs, workflowCard, "No workflow runs returned."),
      renderColumn("Approvals", data.approvals, approvalCard, "No approval records returned."),
    );
  }

  function injectControlPlane() {
    const main = document.querySelector("main");
    const hero = document.querySelector(".hero");
    if (!main || !hero || document.getElementById("control-plane")) return;

    const panel = buildPanel(
      "Control Amosclaud Bot, Autonomous, and Fixer from one website.",
      "Open a project card to see its issues, pull requests, workflows, approvals, and command controls without searching through separate GitHub screens.",
    );
    panel.id = "control-plane";

    const summary = element("div", "control-summary");
    [
      ["Bot", "Command routing and progress"],
      ["Autonomous", "Planning and goal execution"],
      ["Fixer", "Diagnosis, repair, tests, and rollback"],
      ["Doctor", "Final evidence and publication authority"],
    ].forEach(([name, description]) => {
      const card = element("article");
      card.append(statusPill("CONNECTED", "success"), element("strong", "", name), element("span", "", description));
      summary.append(card);
    });

    const projectsHeading = element("div", "section-heading-row");
    const projectsCopy = element("div");
    projectsCopy.append(element("p", "eyebrow", "Projects"), element("h2", "", "Repository command cards"));
    projectsHeading.append(projectsCopy);
    const projects = element("div", "project-grid");

    const workspace = element("section", "workspace-shell");
    workspace.id = "workspace";
    const workspaceHeading = element("div", "section-heading-row");
    const workspaceCopy = element("div");
    workspaceCopy.append(element("p", "eyebrow", "Project workspace"), element("h2", "", state.selectedRepository));
    workspaceCopy.querySelector("h2").id = "workspace-title";
    workspaceHeading.append(workspaceCopy, statusPill("PUBLIC DATA · TOKEN FREE", "success"));
    const workspaceGrid = element("div", "workspace-grid");
    workspaceGrid.id = "workspace-grid";
    workspace.append(workspaceHeading, workspaceGrid);

    panel.append(summary, projectsHeading, projects, workspace);
    hero.after(panel);
    renderRepositoryCards(projects);
    renderWorkspace();
  }

  async function loadRepository(repository) {
    const base = `https://api.github.com/repos/${repository.fullName}`;
    try {
      const [metadata, issuesRaw, pulls, runsRaw] = await Promise.all([
        githubJson(base),
        githubJson(`${base}/issues?state=open&per_page=20`),
        githubJson(`${base}/pulls?state=open&per_page=10`),
        githubJson(`${base}/actions/runs?per_page=10`),
      ]);
      const issues = issuesRaw.filter((item) => !item.pull_request);
      const runs = Array.isArray(runsRaw.workflow_runs) ? runsRaw.workflow_runs : [];
      const latest = runs[0];
      const approvals = issuesRaw.filter((item) => /approval required|amosclaud approval/i.test(item.title || ""));
      state.repositories.set(repository.fullName, {
        defaultBranch: metadata.default_branch,
        openIssues: metadata.open_issues_count ?? issues.length,
        openPulls: pulls.length,
        issues,
        pulls,
        runs,
        approvals,
        workflowLabel: latest ? (latest.conclusion || latest.status || "unknown").toUpperCase() : "NO RUNS",
        workflowTone: latest ? workflowTone(latest.conclusion, latest.status) : "queued",
      });
    } catch (error) {
      state.repositories.set(repository.fullName, {
        defaultBranch: "Unavailable",
        openIssues: "—",
        openPulls: "—",
        issues: [],
        pulls: [],
        runs: [],
        approvals: [],
        workflowLabel: "UNAVAILABLE",
        workflowTone: "failure",
        error: String(error),
      });
    }
  }

  async function start() {
    injectControlPlane();
    await Promise.all(repositories.map(loadRepository));
    const projects = document.querySelector(".project-grid");
    if (projects) renderRepositoryCards(projects);
    renderWorkspace();
  }

  start();
})();
