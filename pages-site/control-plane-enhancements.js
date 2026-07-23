(() => {
  "use strict";

  const validRepository = (value) => /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value);
  const text = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  };

  function installToolbar() {
    const plane = document.getElementById("control-plane");
    const workspace = document.getElementById("workspace");
    if (!plane || !workspace || document.getElementById("control-tools")) return;

    const tools = text("section", "control-tools");
    tools.id = "control-tools";

    const heading = text("div", "control-tools-copy");
    heading.append(
      text("p", "eyebrow", "Useful controls"),
      text("h2", "", "Find the work that needs attention"),
      text("p", "section-copy", "Search visible cards, filter by state, refresh live GitHub data, or preview another public repository without supplying a token."),
    );

    const controls = text("div", "control-tools-grid");
    const searchLabel = text("label", "control-field", "Search workspace");
    const search = text("input");
    search.id = "workspace-search";
    search.type = "search";
    search.placeholder = "Issue, pull request, workflow, approval…";
    searchLabel.append(search);

    const filterLabel = text("label", "control-field", "Show state");
    const filter = text("select");
    filter.id = "workspace-filter";
    [["all", "All records"], ["failure", "Failures"], ["running", "Running / waiting"], ["success", "Successful"], ["approval", "Approvals"]].forEach(([value, label]) => {
      const option = text("option", "", label);
      option.value = value;
      filter.append(option);
    });
    filterLabel.append(filter);

    const repositoryLabel = text("label", "control-field", "Preview public repository");
    const repositoryWrap = text("span", "repository-preview-control");
    const repository = text("input");
    repository.id = "repository-preview";
    repository.placeholder = "owner/repository";
    repository.autocomplete = "off";
    const preview = text("button", "button button-small", "Preview");
    preview.type = "button";
    repositoryWrap.append(repository, preview);
    repositoryLabel.append(repositoryWrap);

    const refresh = text("button", "button button-small button-secondary", "Refresh live data");
    refresh.id = "refresh-control-plane";
    refresh.type = "button";

    controls.append(searchLabel, filterLabel, repositoryLabel, refresh);
    const status = text("p", "control-live-status", "Live public GitHub data · no token supplied");
    status.id = "control-live-status";
    tools.append(heading, controls, status);
    plane.insertBefore(tools, workspace);

    const applyFilters = () => {
      const query = search.value.trim().toLowerCase();
      const mode = filter.value;
      let visible = 0;
      document.querySelectorAll("#workspace-grid .workspace-item").forEach((card) => {
        const cardText = card.textContent.toLowerCase();
        const matchesText = !query || cardText.includes(query);
        const matchesMode = mode === "all"
          || (mode === "approval" && card.classList.contains("approval-item"))
          || (mode === "failure" && /FAIL|FAILURE|CANCELLED|TIMED_OUT/.test(card.textContent))
          || (mode === "running" && /RUNNING|WAITING|QUEUED|IN_PROGRESS/.test(card.textContent))
          || (mode === "success" && /SUCCESS|PASS|COMPLETED|RECORDED/.test(card.textContent));
        card.hidden = !(matchesText && matchesMode);
        if (!card.hidden) visible += 1;
      });
      status.textContent = `${visible} visible record${visible === 1 ? "" : "s"} · live public GitHub data · no token supplied`;
    };

    search.addEventListener("input", applyFilters);
    filter.addEventListener("change", applyFilters);

    refresh.addEventListener("click", () => {
      refresh.disabled = true;
      status.textContent = "Refreshing live GitHub data…";
      window.location.reload();
    });

    preview.addEventListener("click", async () => {
      const name = repository.value.trim();
      if (!validRepository(name)) {
        status.textContent = "Enter a public repository as owner/name.";
        repository.focus();
        return;
      }
      preview.disabled = true;
      status.textContent = `Loading ${name}…`;
      try {
        const response = await fetch(`https://api.github.com/repos/${name}`, { headers: { Accept: "application/vnd.github+json" } });
        if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
        const data = await response.json();
        const card = text("article", "repository-preview-card");
        const top = text("div", "workspace-item-header");
        top.append(text("strong", "", data.full_name), text("span", "control-pill success", "PUBLIC"));
        const description = text("p", "", data.description || "No repository description provided.");
        const metrics = text("div", "preview-metrics");
        [["Default branch", data.default_branch], ["Open issues", data.open_issues_count], ["Language", data.language || "Unknown"], ["Updated", new Date(data.updated_at).toLocaleDateString()]].forEach(([label, value]) => {
          const item = text("span");
          item.append(text("strong", "", String(value)), text("small", "", label));
          metrics.append(item);
        });
        const actions = text("div", "project-actions");
        ["inspect", "health", "verify"].forEach((action) => {
          const button = text("button", "button button-small", action);
          button.type = "button";
          button.addEventListener("click", () => {
            document.getElementById("request-type").value = action;
            document.getElementById("request-title").value = `${action[0].toUpperCase()}${action.slice(1)} ${name}`;
            document.getElementById("request-body").value = `Target repository: ${name}\n\nDescribe the objective, expected result, and evidence.`;
            ["request-type", "request-title", "request-body"].forEach((id) => document.getElementById(id).dispatchEvent(new Event("input", { bubbles: true })));
            document.getElementById("submit").scrollIntoView({ behavior: "smooth" });
          });
          actions.append(button);
        });
        card.append(top, description, metrics, actions);
        document.getElementById("repository-preview-result")?.remove();
        card.id = "repository-preview-result";
        tools.append(card);
        status.textContent = `${name} is available for public preview. Write access still requires GitHub App approval.`;
      } catch (error) {
        status.textContent = `Repository preview unavailable: ${error.message}`;
      } finally {
        preview.disabled = false;
      }
    });

    const observer = new MutationObserver(applyFilters);
    observer.observe(document.getElementById("workspace-grid"), { childList: true, subtree: true });
    applyFilters();
  }

  const timer = window.setInterval(() => {
    if (document.getElementById("control-plane")) {
      window.clearInterval(timer);
      installToolbar();
    }
  }, 100);
})();
