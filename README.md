<div align="center">

# Amosclaud

**An autonomous software programming platform for building, understanding, running, testing, debugging, repairing, verifying, and operating real software.**

Amosclaud combines a programming-language project, a self-agent programmer, a cloud development workspace, execution runtimes, repository automation, verification, and deployment controls into one developer system.

[Quickstart](docs/QUICKSTART.md) · [Programming Language](docs/AMOSCLAUD_LANGUAGE.md) · [Self-Agent Programmer](docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md) · [Terminal](docs/AMOSCLAUD_TERMINAL.md) · [Pipeline](docs/PIPELINE_ECOSYSTEM.md) · [Contributing](CONTRIBUTING.md)

</div>

## Truth and evidence policy

Amosclaud documentation separates **verified capability** from **implemented code**, **work in progress**, and **roadmap**. Source code, a branch, or a pull request is evidence that work exists; it is not by itself proof that a production service is healthy or that a feature works end-to-end.

Status meanings:

- ✅ **Verified** — implementation exists and there is relevant execution/test/runtime evidence.
- 🟡 **Implemented / verification pending** — implementation exists, but current end-to-end or production verification is incomplete.
- 🚧 **In progress** — implementation is being developed or remains in an unmerged change.
- ❌ **Not available yet** — Amosclaud must not advertise this as a current capability.

## Current capability and proof

| Capability | Status | Evidence / limitation |
|---|---|---|
| Repository/platform source | ✅ Verified | This repository contains the Amosclaud services, APIs, agent, workspace, verification, deployment and integration source. |
| GitHub repository integration | ✅ Verified | Amosclaud currently uses GitHub repository, issue, pull-request and workflow integration. GitHub is still part of the current operating path. |
| Browser terminal/workspace foundation | 🟡 Implemented / verification pending | The cloud-terminal/agent-workspace implementation was merged in PR #763. A merged implementation does not prove every hosted terminal path is currently healthy. |
| Repository inspection and engineering automation | 🟡 Implemented / verification pending | Agent, repository, code-analysis, repair and verification components exist. Individual autonomous tasks still require real execution evidence before being reported as successful. |
| Native issue-command execution | 🚧 In progress | The native issue-action execution fix is tracked in PR #1209 and is not treated here as a completed capability until merged and verified. |
| Amosclaud Applications and integration settings | 🚧 In progress | The Applications/Integrations implementation is tracked in PR #1205 and is not treated as generally available until merged and verified. |
| Amosclaud Programming Language `.amos` | 🚧 In progress | The language specification exists. A complete lexer/parser/runtime/toolchain has not yet been implemented and verified. |
| Self-Agent Programmer | 🚧 In progress | Existing agent/workspace/verification foundations support this direction, but the complete contract described in the specification is not yet verified end-to-end. |
| Fully independent Amosclaud CI/action system | ❌ Not available yet | GitHub Actions/workflows remain in current repository automation. Amosclaud must not claim they have been completely replaced. |
| Fully independent hosting/infrastructure | ❌ Not available yet | Current hosted operation still uses third-party infrastructure. Self-hosting foundations exist, but Amosclaud is not yet fully provider-independent in production. |
| Universal third-party installable agent | ❌ Not available yet | A third-party system cannot be assumed to support Amosclaud until an authorized connector/application/runner and its permissions are configured. |
| Guaranteed autonomous build → fix → PR → deploy for every task | ❌ Not available yet | Every stage depends on repository permissions, execution environment, tests, infrastructure and deployment state. Amosclaud reports the real stage reached instead of guaranteeing success. |

## Third-party system boundary

Amosclaud can interact with a third-party system only through an integration, API, repository connection, application, runner, connector, credential broker, or other authority that the system and user actually provide. Amosclaud does not gain access merely because an agent requests it.

For third-party environments, Amosclaud can currently be used around repository integration, workspace/terminal foundations, engineering automation, verification components and hosted/self-hosted execution components where configured. It cannot truthfully claim universal read/write access, universal deployment access, provider independence, or a fully installable native Amosclaud agent across arbitrary external systems yet.

## What Amosclaud is

Amosclaud is being built as a complete computer-programming ecosystem rather than only a chat assistant or CI wrapper. The long-term product contract is simple: a developer should be able to describe or write a program, give Amosclaud an authorized workspace, and receive real files, execution, tests, diagnostics, verified changes, applications, and deployment evidence.

The ecosystem has four primary layers:

1. **Amosclaud Programming Language** — the `.amos` language, language specification, parser/runtime project, modules, tooling, and interoperability contract.
2. **Amosclaud Self-Agent Programmer** — the autonomous engineering agent that plans work, reads and edits repositories, uses terminals, runs tests, debugs failures, verifies results, and can prepare governed repository or deployment actions.
3. **Amosclaud SpaceCodeMe** — the cloud development workspace for files, editors, terminals, ports, problems, connectors, builds, debugging, and agent collaboration.
4. **Amosclaud Control Plane** — identity, organizations, repositories, applications, integrations, tokens, execution nodes, pipelines, storage, observability, approvals, and policy.

These are product architecture and direction. Each individual capability must satisfy the evidence policy above before being represented as verified.

## Programming with Amosclaud

The Amosclaud language project uses `.amos` as its source-file identity. Its goal is to support ordinary deterministic programs and first-class software-engineering automation through the same language family.

A representative **target** syntax is:

```text
program HelloAmosclaud

let name = "developer"
print("Hello, " + name)

agent programmer {
    objective "Build and verify this project"
    workspace "."
    verify tests
}
```

This is a language contract under development, not proof that these constructs execute today. See [docs/AMOSCLAUD_LANGUAGE.md](docs/AMOSCLAUD_LANGUAGE.md).

## Amosclaud Self-Agent Programmer

The intended engineering execution cycle is:

```text
Developer request
      ↓
Understand + plan
      ↓
Inspect repository/workspace
      ↓
Create or edit files
      ↓
Run / build / test / lint / debug
      ↓
Diagnose failures and repair
      ↓
Verify evidence
      ↓
Return files, patch, application, PR, deployment, or report
```

The complete cycle is a target contract, not a guarantee that every current task can complete every stage. Consequential operations remain permission-aware. See [docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md](docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md).

## Existing engineering foundation

The repository contains repository APIs, autonomous-agent services, cloud-terminal code, software creation and code-analysis services, verification and repair workflows, Docker/self-hosting support, GitHub integration, pipeline orchestration, execution-node concepts, telemetry and deployment tooling.

Those statements describe repository evidence. Runtime health, deployment health and successful autonomous execution require separate current evidence.

## Local quickstart

### Prerequisites

- Python 3.11+
- Git
- Docker with Docker Compose for the complete self-hosted runtime

```bash
git clone https://github.com/wamakologeorge-dev/amosclaude-clean.git
cd amosclaude-clean
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
```

Repository inspection entry point:

```bash
amosclaud-quick . --objective "Inspect this project and identify the most important failure"
```

Local API/application entry point:

```bash
python -m amoscloud_ai.main
```

Then open `http://127.0.0.1:8000` if startup succeeds in your environment.

Repository validation commands include:

```bash
make test
make quality
make build
```

These commands are instructions, not a claim that the latest run passed. Check the command output and current CI evidence.

## Self-hosted runtime

```bash
cp .env.example .env
mkdir -p AmosclaudWorkspace
docker compose -f docker-compose.selfhost.yml up -d
curl --fail http://127.0.0.1:8000/health
```

A successful health request is evidence for that running environment only. It does not automatically prove all Amosclaud services or hosted deployments are healthy.

## Verification-first engineering

Amosclaud must never equate generated code with completed software. Work is considered verified only when the requested result has appropriate evidence: files exist, relevant commands actually execute, builds/tests/checks report their results, failures are surfaced, and consequential actions report their real state.

The agent should use language such as `planned`, `changed`, `executed`, `verified`, `blocked`, or `failed` instead of collapsing those states into "done."

## Repository automation

GitHub remains a supported and currently important repository integration. Amosclaud can use repository events and workflows while native Amosclaud application, action, token, workspace, agent and execution contracts continue to develop.

Protected writes and deployments remain governed operations. A model or agent should not receive unrestricted credentials merely because it can generate a patch.

## Project status

Amosclaud is under active development. `main` is the canonical repository product branch. Feature branches and pull requests are proposed work until merged. A merge is still not production verification; deployment and runtime evidence remain separate.

The programming-language layer is an explicit product direction and specification effort. It must be implemented and tested incrementally before Amosclaud can truthfully be described as a mature general-purpose programming language.

## Documentation

- [Programming Language](docs/AMOSCLAUD_LANGUAGE.md)
- [Self-Agent Programmer](docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md)
- [Quickstart](docs/QUICKSTART.md)
- [Amosclaud Terminal](docs/AMOSCLAUD_TERMINAL.md)
- [Desktop gateway](docs/AMOSCLAUD_DESKTOP_GATEWAY.md)
- [Pipeline ecosystem](docs/PIPELINE_ECOSYSTEM.md)
- [Developer fast path](docs/DEVELOPER_FAST_PATH.md)
- [Production deployment](DEPLOYMENT.md)
- [Contributing](CONTRIBUTING.md)

## Contributing

Contributions are welcome across the language, runtime, agent, editor/workspace, APIs, verification, testing, infrastructure, documentation, security and developer experience. Documentation changes should preserve the evidence policy: do not promote planned or unverified functionality to verified capability.

## License

Repository source code is available under the [MIT License](LICENSE). Separate [commercial service terms](LICENSE-COMMERCIAL.txt) apply to paid, hosted, managed, supported, or enterprise Amosclaud offerings without removing rights already granted for MIT-licensed source code.
