# Amosclaud Vision — George's Canonical Doctrine (2026-08-28)

**Source:** George Wamakolo, verbatim intent, 2026-08-28. This supersedes narrower framings.

## North Star
Amosclaud becomes an **independent software-programming provider and computing platform** — bigger than a chatbot, GitHub bot, coding assistant, or website. Any person, developer, company, AI agent, or application can say **"Build this for me"** and Amosclaud takes it from idea to working software.

## Complete lifecycle owned by the platform
Idea → Requirements → Plan → Code → Files → Terminal → Build → Test → Debug → Repair → Security → Review → Application → Deployment → Monitoring → Maintenance → Improvement — without moving between ten products.

## The 17 pillars
1. **Amosclaud Agent — the programmer.** Does engineering work, not snippets. "Create an inventory system" → asks questions, architects, codes, tests, repairs, presents. "Login page stopped working" → reproduces, locates, repairs, verifies with evidence.
2. **SpaceCodeMe — the development computer.** Browser-based workspace: editor + files + terminal + Git + runtime + containers + debugger + preview + DBs + env vars + Agent. Human and Agent share the same files/terminal — real pair programming. Desktop version later.
3. **Projects.** Everything lives in a project: repo, workspace, agent conversations, tasks, applications, deployments, DBs, storage, secrets, logs, domains. Agent knows "we are working on Project X" with full history.
4. **Organizations.** Companies create orgs containing owners/admins/developers/agents/applications/external collaborators. Org-controlled permissions.
5. **Applications.** Developer-built apps that request scoped capabilities (e.g. Database Doctor requests repositories:read, agent:invoke, terminal:execute, storage:read). Orgs install with consent screen. Scoped identity per install. Build once, thousands install → developer ecosystem.
6. **Marketplace.** Publish agent tools, dev tools, deploy providers, DB tools, security scanners, themes, SpaceCodeMe extensions, automation packs, models, monitoring, business apps. Free + paid. Economic reason to build for Amosclaud.
   - **Integrations principle:** GitHub becomes ONE integration, not the foundation. External service → Amosclaud Integration Gateway → Amosclaud. Amosclaud remains the control plane; integrations add capabilities, never own the platform.
7. **API.** Everything has an API: projects, repos, files, tasks, agents, applications, orgs, SpaceCodeMe, deployments, storage, models, actions, logs. **Other AI agents use Amosclaud via Amosclaud credentials** (not direct GitHub access) — org authorizes per-capability, incl. explicit DENY (e.g. production deploy: DENIED). Amosclaud records everything.
8. **Identity.** User, Organization, Agent, Application, Service, Machine/Runner identities. Every operation has an accountable actor: "Application Deployment Manager, acting for Org Acme, changed server.py through SpaceCodeMe workspace #123 using repositories:write."
9. **Permissions.** Capabilities, not full access: repository.read/write, terminal.execute, agent.invoke, spacecodeme.use, actions.run, deployment.staging, deployment.production, storage.read/write, secrets.use, models.invoke. Scoped: Org → Project → Workspace → Environment → Capability.
10. **Actions.** First-party automation: on code change → build, test, security checks, Agent diagnoses failures, container, staging deploy, health verify. Runs on Amosclaud's own runners. GitHub Actions supported via integration but not required.
11. **Runners.** Amosclaud Cloud Runner, self-hosted, developer computer, org server, GPU runner. Task → control plane → scheduler → isolated workspace → execute → evidence → Amosclaud. George's future physical servers become execution nodes.
13. **Model gateway.** Agent asks the Amosclaud model layer; behind it: Amosclaud models, local models, org models, third-party. Platform doesn't care which model reasoned.
14. **Memory.** Project knowledge, not chat history: "uses PostgreSQL", "prod runs Python 3.13", "owner forbids direct prod deploys", "this error was fixed with X". Permission-controlled, attributable. User/Project/Org/Agent/Application memories that never leak into each other.
15. **Terminal.** Controlled execution interface for humans, Agent, authorized Applications, external Agents. Amosclaud decides: "Agent may run pytest" / "Agent may NOT delete the production DB."
16. **Repository provider.** Amosclaud hosts its own repos. GitHub/GitLab connectable but not required. Key independence step.
17. **Deployment.** Repo → build → artifact/container → environment → deploy → domain → HTTPS → health → logs → monitoring. "Deploy this application" → Agent DOES it, never replies with manual instructions.

18. **Domains & networking.** Projects manage domains, subdomains, DNS, TLS, ports, gateways, service routing, firewall policies. Example: Project "Store" → store.example.com with routes `/` → frontend, `/api` → API, `/agent` → agent service. Part of the project, not scattered across providers.
19. **Databases & storage.** Projects create/connect SQL DBs, key/value stores, object storage, file storage, buckets, caches, backups. Agent can say "this project needs PostgreSQL" and — with authorization — provision it.
20. **Security & Quality — Claim vs Evidence.** Every change: code analysis → dependency scan → secret detection → tests → policy checks → Agent review → deployment verification. Core doctrine: Amosclaud must distinguish **claim** from **evidence**. "Tests passed" requires a real test execution proving it. "Deployment succeeded" requires deploy + health evidence. Crucial for autonomous programming.
21. **Amosclaud Doctor.** Repair system grows into a general engineering Doctor: Detect → Diagnose → Reproduce → Repair → Verify → Record → Learn. Example: prod returns 500 → Doctor gathers logs → Agent finds regression → repair produced → tests run → staging verifies → production authorization requested if policy requires.
22. **Monitoring & observability.** Post-deploy, projects expose logs, metrics, traces, errors, resource usage, deploy history, agent/application activity, security events. Agent receives system events ("error rate 0.2% → 14%") and investigates automatically. Moves Amosclaud from software creation into software **operation**.
23. **Human approval policies.** Autonomy ≠ no control. Orgs define policy: Agent may auto-inspect/edit dev files/run tests/repair failed tests; approval required for prod DB creation, billing changes, sensitive secrets, prod deploys, infra deletion. Different autonomy levels per org.
24. **Amosclaud Desktop.** Local gateway into the same ecosystem: connects local files + terminal + local models + Docker + local hardware to the user's Amosclaud org. Same Agent operates cloud SpaceCodeMe OR the developer's own computer, by permission.
25. **Amosclaud CLI.** Terminal-native interface to the same API: `amosclaud login / project create / space open / agent "fix the failing tests" / test / deploy staging / logs / app create`. One architecture for every interface.
26. **Amosclaud SDK.** Programmable platform: `from amosclaud import Amosclaud; amos.projects.get("store").agent.run("Add product search and verify it.")`. Businesses embed Amosclaud programming into their own products.
27. **Amosclaud as a provider.** The unifying shift: from "where is my repository?" to "where is my **project**?" Project = repository + workspace + Agent + infrastructure + deployments + memory + applications + permissions + operational history. Architecture: Identity/Permissions/Orgs → Project Control → {Repository, SpaceCodeMe, Applications} → Agent + Actions → Model/Memory + Runner Network → Build/Test/Fix → Deploy → Domain/Database/Storage → Monitoring → Doctor.

## Repo-confirmed additions (discovered 2026-08-28 sweep)

28. **Amosclaud Programming Language** — `.amos` files; deterministic core + governed `agent { }` blocks; verification as a language primitive (`verify { run "pytest" require exit_code == 0 }`); CLI roadmap `amos run/check/fmt`; stdlib `amos::agent`, `amos::verify`, `amos::repo`. Spec: `docs/AMOSCLAUD_LANGUAGE.md` (merged PR #1212). Spec explicitly states: appearing in the spec ≠ implemented.
29. **Self-Agent Programmer** — the agent execution contract: four evidence states (**planned → changed → executed → verified**); authority envelopes (`workspace.read`, `terminal.execute`, `deployment.execute`…); bounded loop budgets; SpaceCodeMe as primary surface. Spec: `docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md`.
30. **Truth & evidence policy in README** — capability matrix with ✅ Verified / 🟡 Implemented-unverified / 🚧 In progress / ❌ Not yet. Pillar 20 formalized in the repo's front page.
31. **workspace_worker/** — real SpaceCodeMe container backend: FastAPI service, token-auth, Docker provision/start/stop/restart/delete per workspace (`workspace_worker/app.py`, `runtime.py` 405 lines). Shipped in George's 3,126-file ecosystem commit `02c399d`.

## Standing implications for the agent
- Prioritize features that reduce GitHub/Railway dependence over features that deepen it.
- Every new capability should map to a pillar above; name the pillar in PR descriptions.
- Applications/scopes work (PR #1205 lineage, SCOPE_CATALOG) is pillar 5 — foundational, keep it healthy.
- Identity/permissions decisions must anticipate pillar 8/9 (actor attribution, capability scoping).
