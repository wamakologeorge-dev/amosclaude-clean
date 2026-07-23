(() => {
  "use strict";

  const hubRepository = "wamakologeorge-dev/Amosclaud1";
  const engineRepository = "wamakologeorge-dev/amosclaude-clean";
  const exampleIssue = 6;
  const form = document.querySelector("#request-form");
  const type = document.querySelector("#request-type");
  const title = document.querySelector("#request-title");
  const body = document.querySelector("#request-body");
  const trusted = document.querySelector("#trusted-role");
  const preview = document.querySelector("#command-preview");
  const warning = document.querySelector("#role-warning");
  const issueList = document.querySelector("#issue-list");
  const timeline = document.querySelector("#command-timeline");

  const restrictedCommands = new Set(["fix", "mission"]);
  const commandPrefix = {triage:"@amosclaud triage",inspect:"@amosclaud inspect",health:"@amosclaud health",goal:"@amosclaud goal",verify:"@amosclaud verify",fix:"@amosclaud fix",mission:"@amosclaud mission"};
  const plans = [
    {name:"Community",price:"Free",badge:"Start here",description:"Public issue workflows for triage, inspection, health, and verification.",features:["Public repositories","Issue request builder","Read-only workflows","Community support"],action:"Request Community access"},
    {name:"Builder",price:"Paid plan",badge:"Individuals",description:"Install Amosclaud on repositories you select and run governed engineering missions.",features:["Selected repositories","Verified repair and PRs","Mission checkpoints","Execution limits"],action:"Join Builder early access"},
    {name:"Team",price:"Paid plan",badge:"Recommended",description:"Shared autonomous workflows with role controls and repository health.",features:["Organization installation","Team permissions","Approved shared lessons","Priority capacity"],action:"Join Team early access",featured:true},
    {name:"Enterprise",price:"Custom",badge:"Organizations",description:"Private governed deployment for larger organizations.",features:["Private repositories","Custom budgets","Audit controls","Dedicated onboarding"],action:"Discuss Enterprise"}
  ];

  function commandText() {
    const objective = body.value.trim() || title.value.trim();
    const base = commandPrefix[type.value] || "@amosclaud inspect";
    return type.value === "triage" || type.value === "health" ? base : (objective ? `${base} ${objective}` : base);
  }

  function updatePreview() {
    const restricted = restrictedCommands.has(type.value);
    preview.textContent = commandText();
    warning.classList.toggle("restricted", restricted);
    warning.textContent = restricted
      ? (trusted.checked ? "The Bot will independently verify your GitHub role and every approval, Doctor, and verification gate." : "Restricted request: acknowledge the role requirement before continuing. GitHub enforcement still happens inside the Bot.")
      : "Public requests are safe by default. Restricted commands are rejected unless GitHub confirms a trusted role.";
  }

  [type, title, body, trusted].forEach((element) => { element.addEventListener("input", updatePreview); element.addEventListener("change", updatePreview); });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const restricted = restrictedCommands.has(type.value);
    if (restricted && !trusted.checked) { warning.textContent = "Confirm the trusted-role acknowledgement before preparing this request."; warning.classList.add("restricted"); trusted.focus(); return; }
    const issueBody = [
      "## Amosclaud Agent Issue Hub request","",`**Request type:** ${type.options[type.selectedIndex].text}`,`**Execution target:** ${engineRepository}`,"","### Objective and evidence",body.value.trim(),"","### Bot command","```text",commandText(),"```","",
      restricted ? "> This request may change repository state. Amosclaud must verify trusted GitHub authority and all approval and verification gates." : "> This request is read-only or planning-oriented unless a trusted collaborator later authorizes a governed write action.","",
      "_Prepared by the static Amosclaud Agent Issue Hub. No GitHub token was collected or stored._"
    ].join("\n");
    const params = new URLSearchParams({title:`[Agent Hub] ${title.value.trim()}`,body:issueBody,labels:"amosclaud-command"});
    window.location.href = `https://github.com/${hubRepository}/issues/new?${params.toString()}`;
  });

  function planIssueUrl(plan) {
    const issueBody = ["## Amosclaud package and installation request","",`**Selected package:** ${plan.name}`,`**Plan type:** ${plan.price}`,"","I want to install the Amosclaud GitHub App on repositories I explicitly approve.","","### Required safeguards","- GitHub App installation instead of a pasted personal access token","- Access limited to repositories selected in GitHub","- Minimum permissions","- Short-lived installation tokens only on a secure backend","- Revocable from GitHub at any time","","> This records interest only. Billing and installation activate after the GitHub App and payment service are registered."].join("\n");
    return `https://github.com/${hubRepository}/issues/new?${new URLSearchParams({title:`[Agent Hub Plan] ${plan.name}`,body:issueBody}).toString()}`;
  }

  function renderPlans() {
    const roles = document.querySelector("#roles");
    if (!roles) return;
    const section = document.createElement("section");
    section.id = "plans"; section.className = "section plans-section";
    section.innerHTML = '<p class="eyebrow">Amosclaud packages</p><h2>Install the agent on repositories you approve.</h2><p class="plans-intro">Paid activation will use a GitHub App and approved billing—never a token pasted into this page.</p><div class="plan-grid" id="plan-grid"></div><div class="install-explainer"><strong>Secure installation path</strong><span>Choose plan → Pay securely → Install GitHub App → Select repositories → Receive limited, revocable access.</span></div>';
    const grid = section.querySelector("#plan-grid");
    plans.forEach((plan) => {
      const card = document.createElement("article"); card.className = `plan-card${plan.featured ? " plan-featured" : ""}`;
      const badge = document.createElement("span"); badge.className = "plan-badge"; badge.textContent = plan.badge;
      const heading = document.createElement("h3"); heading.textContent = plan.name;
      const price = document.createElement("p"); price.className = "plan-price"; price.textContent = plan.price;
      const description = document.createElement("p"); description.textContent = plan.description;
      const list = document.createElement("ul"); plan.features.forEach((feature) => { const li = document.createElement("li"); li.textContent = feature; list.append(li); });
      const link = document.createElement("a"); link.className = `button${plan.featured ? "" : " button-secondary"}`; link.href = planIssueUrl(plan); link.textContent = plan.action;
      card.append(badge, heading, price, description, list, link); grid.append(card);
    });
    roles.before(section);
  }

  async function githubJson(url) {
    const response = await fetch(url, {headers:{Accept:"application/vnd.github+json"}});
    if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
    return response.json();
  }

  function extractStatus(comment) {
    const text = String(comment.body || "");
    if (!/Amosclaud/i.test(text) || !/(Status|Verdict):/i.test(text)) return null;
    const status = text.match(/(?:Status|Verdict):\*?\*?\s*([A-Z_]+)/i)?.[1]?.toUpperCase() || "UPDATE";
    const action = text.match(/Action:\s*`([^`]+)`/i)?.[1] || (text.match(/Amosclaud\s+([a-z-]+)\s+(?:result|started)/i)?.[1] || "command");
    const request = text.match(/Request:\s*`([^`]+)`/i)?.[1] || "recorded request";
    const target = text.match(/(?:Target|Repository):\s*`([^`]+)`/i)?.[1] || engineRepository;
    return {status,action,request,target,url:comment.html_url,author:comment.user?.login || "GitHub"};
  }

  function statusClass(status) {
    if (["PASS","SUCCESS","VERIFIED","COMPLETED"].includes(status)) return "success";
    if (["FAIL","FAILED","BLOCKED","ROLLED_BACK"].includes(status)) return "failure";
    if (["RUNNING","REVIEWING","IN_PROGRESS"].includes(status)) return "running";
    return "queued";
  }

  async function loadTimeline() {
    try {
      const pages = await Promise.all([1,2].map((page) => githubJson(`https://api.github.com/repos/${hubRepository}/issues/${exampleIssue}/comments?per_page=100&page=${page}`)));
      const events = pages.flat().map(extractStatus).filter(Boolean).slice(-8).reverse();
      if (!events.length) { timeline.innerHTML = '<p class="loading">No command status events were returned.</p>'; return; }
      timeline.replaceChildren(...events.map((event) => {
        const card = document.createElement("a"); card.className = `timeline-item ${statusClass(event.status)}`; card.href = event.url; card.target = "_blank"; card.rel = "noreferrer";
        const marker = document.createElement("span"); marker.className = "timeline-marker"; marker.textContent = event.status === "PASS" ? "✓" : event.status === "FAIL" ? "!" : "●";
        const content = document.createElement("span"); const heading = document.createElement("strong"); heading.textContent = `${event.status} · ${event.action}`; const meta = document.createElement("small"); meta.textContent = `${event.request} → ${event.target}`; content.append(heading, meta);
        const author = document.createElement("span"); author.className = "timeline-author"; author.textContent = event.author;
        card.append(marker, content, author); return card;
      }));
    } catch (_) { timeline.innerHTML = '<p class="loading">Live command activity is temporarily unavailable. Open issue #6 directly on GitHub.</p>'; }
  }

  async function loadIssues() {
    try {
      const items = (await githubJson(`https://api.github.com/repos/${hubRepository}/issues?state=open&per_page=6`)).filter((item) => !item.pull_request).slice(0,6);
      issueList.replaceChildren(...items.map((item) => {
        const link = document.createElement("a"); link.className = "issue-item"; link.href = item.html_url; link.target = "_blank"; link.rel = "noreferrer";
        const number = document.createElement("span"); number.className = "issue-number"; number.textContent = `#${item.number}`;
        const content = document.createElement("span"); const strong = document.createElement("strong"); strong.textContent = item.title; const small = document.createElement("small"); small.textContent = `Opened by ${item.user?.login || "GitHub user"} · ${item.comments} comments`; content.append(strong,small);
        const state = document.createElement("span"); state.className = "issue-state"; state.textContent = "OPEN"; link.append(number,content,state); return link;
      }));
      if (!items.length) issueList.innerHTML = '<p class="loading">No open public issues were returned.</p>';
    } catch (_) { issueList.innerHTML = '<p class="loading">Live issues are temporarily unavailable. Open Amosclaud1 Issues directly.</p>'; }
  }

  renderPlans(); updatePreview(); loadTimeline(); loadIssues();
})();