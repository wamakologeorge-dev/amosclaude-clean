(() => {
  "use strict";

  const repository = "wamakologeorge-dev/amosclaude-clean";
  const form = document.querySelector("#request-form");
  const type = document.querySelector("#request-type");
  const title = document.querySelector("#request-title");
  const body = document.querySelector("#request-body");
  const trusted = document.querySelector("#trusted-role");
  const preview = document.querySelector("#command-preview");
  const warning = document.querySelector("#role-warning");
  const issueList = document.querySelector("#issue-list");

  const restrictedCommands = new Set(["fix", "mission"]);
  const commandPrefix = {
    triage: "@amosclaud triage",
    inspect: "@amosclaud inspect",
    health: "@amosclaud health",
    goal: "@amosclaud goal",
    verify: "@amosclaud verify",
    fix: "@amosclaud fix",
    mission: "@amosclaud mission",
  };

  function commandText() {
    const objective = body.value.trim() || title.value.trim();
    const base = commandPrefix[type.value] || "@amosclaud inspect";
    if (type.value === "triage" || type.value === "health") return base;
    return objective ? `${base} ${objective}` : base;
  }

  function updatePreview() {
    const restricted = restrictedCommands.has(type.value);
    preview.textContent = commandText();
    warning.classList.toggle("restricted", restricted);
    if (restricted) {
      warning.textContent = trusted.checked
        ? "The page can prepare this request, but the Bot will independently verify your GitHub role and all approval, Doctor, and verification gates."
        : "This is a restricted request. Check the acknowledgement before continuing. GitHub role enforcement still happens inside the Bot.";
    } else {
      warning.textContent = "Public requests are safe by default. Restricted commands are rejected by the Bot unless GitHub confirms a trusted repository role.";
    }
  }

  [type, title, body, trusted].forEach((element) => {
    element.addEventListener("input", updatePreview);
    element.addEventListener("change", updatePreview);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const restricted = restrictedCommands.has(type.value);
    if (restricted && !trusted.checked) {
      warning.textContent = "Confirm the trusted-role acknowledgement before preparing a restricted request.";
      warning.classList.add("restricted");
      trusted.focus();
      return;
    }

    const issueTitle = `[Agent Hub] ${title.value.trim()}`;
    const command = commandText();
    const issueBody = [
      "## Amosclaud Agent Issue Hub request",
      "",
      `**Request type:** ${type.options[type.selectedIndex].text}`,
      "",
      "### Objective and evidence",
      body.value.trim(),
      "",
      "### Bot command",
      "```text",
      command,
      "```",
      "",
      restricted
        ? "> This request may change repository state. Amosclaud must verify OWNER, MEMBER, or COLLABORATOR authority and pass all approval and verification gates."
        : "> This request is read-only or planning-oriented unless a trusted collaborator later authorizes a governed write action.",
      "",
      "_Prepared by the static Amosclaud Agent Issue Hub. The page did not collect a GitHub token or grant repository authority._",
    ].join("\n");

    const params = new URLSearchParams({ title: issueTitle, body: issueBody });
    window.location.href = `https://github.com/${repository}/issues/new?${params.toString()}`;
  });

  function escapeText(value) {
    return String(value ?? "");
  }

  async function loadIssues() {
    try {
      const response = await fetch(`https://api.github.com/repos/${repository}/issues?state=open&per_page=6`, {
        headers: { Accept: "application/vnd.github+json" },
      });
      if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
      const items = (await response.json()).filter((item) => !item.pull_request).slice(0, 6);
      if (!items.length) {
        issueList.innerHTML = '<p class="loading">No open public issues were returned.</p>';
        return;
      }

      issueList.replaceChildren(...items.map((item) => {
        const link = document.createElement("a");
        link.className = "issue-item";
        link.href = item.html_url;
        link.target = "_blank";
        link.rel = "noreferrer";

        const number = document.createElement("span");
        number.className = "issue-number";
        number.textContent = `#${item.number}`;

        const content = document.createElement("span");
        const strong = document.createElement("strong");
        strong.textContent = escapeText(item.title);
        const small = document.createElement("small");
        const author = item.user?.login || "GitHub user";
        small.textContent = `Opened by ${author} · ${item.comments} comment${item.comments === 1 ? "" : "s"}`;
        content.append(strong, small);

        const state = document.createElement("span");
        state.className = "issue-state";
        state.textContent = "OPEN";
        link.append(number, content, state);
        return link;
      }));
    } catch (error) {
      issueList.innerHTML = '<p class="loading">Live issues are temporarily unavailable. Use “View all issues” to open GitHub directly.</p>';
    }
  }

  updatePreview();
  loadIssues();
})();
