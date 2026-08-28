<div align="center">

# Amosclaud

**An autonomous software programming platform for building, understanding, running, testing, debugging, repairing, verifying, and operating real software.**

Amosclaud combines a programming-language project, a self-agent programmer, a cloud development workspace, execution runtimes, repository automation, verification, and deployment controls into one developer system.

[Quickstart](docs/QUICKSTART.md) · [Programming Language](docs/AMOSCLAUD_LANGUAGE.md) · [Self-Agent Programmer](docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md) · [Terminal](docs/AMOSCLAUD_TERMINAL.md) · [Pipeline](docs/PIPELINE_ECOSYSTEM.md) · [Contributing](CONTRIBUTING.md)

</div>

## What Amosclaud is

Amosclaud is being built as a complete computer-programming ecosystem rather than only a chat assistant or CI wrapper. The long-term product contract is simple: a developer should be able to describe or write a program, give Amosclaud an authorized workspace, and receive real files, execution, tests, diagnostics, verified changes, applications, and deployment evidence.

The ecosystem has four primary layers:

1. **Amosclaud Programming Language** — the `.amos` language, language specification, parser/runtime project, modules, tooling, and interoperability contract.
2. **Amosclaud Self-Agent Programmer** — the autonomous engineering agent that plans work, reads and edits repositories, uses terminals, runs tests, debugs failures, verifies results, and can prepare governed repository or deployment actions.
3. **Amosclaud SpaceCodeMe** — the cloud development workspace for files, editors, terminals, ports, problems, connectors, builds, debugging, and agent collaboration.
4. **Amosclaud Control Plane** — identity, organizations, repositories, applications, integrations, tokens, execution nodes, pipelines, storage, observability, approvals, and policy.

These layers are designed to work together without pretending unfinished functionality is already production-ready. Documentation distinguishes implemented foundations from active development and planned capabilities.

## Programming with Amosclaud

The Amosclaud language project uses `.amos` as its source-file identity. Its goal is to support ordinary deterministic programs and first-class software-engineering automation through the same language family.

A representative target syntax is:

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

This syntax is a language contract under development, not a claim that every construct above is already implemented. The language roadmap includes lexical analysis, parsing, an executable runtime, functions, modules, packages, types, async tasks, process and filesystem APIs, tests, formatting, diagnostics, debugging, language-server support, package management, and controlled agent instructions.

See [docs/AMOSCLAUD_LANGUAGE.md](docs/AMOSCLAUD_LANGUAGE.md).

## Amosclaud Self-Agent Programmer

The Self-Agent Programmer is the engineering execution layer. Instead of stopping at generated text, its intended work cycle is:

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

Consequential operations remain permission-aware. Repository writes, credentials, production deployment, protected branches, organization resources, and other sensitive operations must stay within the authority granted to the agent.

See [docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md](docs/AMOSCLAUD_SELF_AGENT_PROGRAMMER.md).

## SpaceCodeMe development computer

The repository already contains the foundation for a browser-accessible development workspace with persistent terminal sessions, project tools, execution isolation, debugging, ports, problems, connectors, network diagnostics, Git operations, and agent collaboration.

The product direction is a desktop-style programming environment where a developer can move between projects, repositories, files, terminals, Amosclaud Agent, applications, integrations, deployments, logs, and settings without treating GitHub or a hosting provider as the Amosclaud user interface.

## Existing engineering foundation

Amosclaud already contains substantial platform infrastructure, including repository APIs, autonomous-agent services, cloud-terminal code, software creation and code-analysis services, verification and repair workflows, Docker/self-hosting support, GitHub integration, pipeline orchestration, execution-node concepts, telemetry, and deployment tooling.

Some capabilities require external infrastructure or configuration to operate fully. A merged source implementation also does not by itself prove that a hosted deployment is healthy. Runtime status must be established from real verification and deployment evidence.

## Five-minute local quickstart

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

Run deterministic repository inspection:

```bash
amosclaud-quick . --objective "Inspect this project and identify the most important failure"
```

Start the local API/application:

```bash
python -m amoscloud_ai.main
```

Then open `http://127.0.0.1:8000`.

Validate the repository:

```bash
make test
make quality
make build
```

## Self-hosted runtime

```bash
cp .env.example .env
mkdir -p AmosclaudWorkspace
docker compose -f docker-compose.selfhost.yml up -d
curl --fail http://127.0.0.1:8000/health
```

Amosclaud is designed so execution can ultimately live on Amosclaud-controlled infrastructure or a developer-authorized machine. External providers may be integrations or execution targets; they do not define the Amosclaud product architecture.

## Verification-first engineering

Amosclaud should never equate generated code with completed software. Work is considered complete only when the requested result has appropriate evidence: files exist, commands execute, builds complete, tests or checks run, failures are surfaced, and consequential actions report their real state.

That verification principle applies equally to human-written code, `.amos` programs, Self-Agent Programmer changes, pull requests, deployments, and autonomous repair.

## Repository automation

GitHub remains a supported repository integration. Amosclaud can use repository events and workflows while the native platform evolves toward its own application, action, token, workspace, agent, and execution contracts.

Protected writes and deployments remain governed operations. The model or agent should not receive unrestricted credentials merely because it can generate a patch.

## Project status

Amosclaud is under active development. `main` is the canonical repository product branch. Feature branches and pull requests represent proposed work until merged and verified.

The programming-language layer described here is now an explicit product direction and specification effort. It must be implemented and tested incrementally before Amosclaud can truthfully be described as a mature general-purpose programming language.

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

Contributions are welcome across the language, runtime, agent, editor/workspace, APIs, verification, testing, infrastructure, documentation, security, and developer experience. Changes should produce evidence and strengthen the shared Amosclaud architecture rather than advertise capabilities that cannot yet be demonstrated.

## License

Repository source code is available under the [MIT License](LICENSE). Separate [commercial service terms](LICENSE-COMMERCIAL.txt) apply to paid, hosted, managed, supported, or enterprise Amosclaud offerings without removing rights already granted for MIT-licensed source code.
