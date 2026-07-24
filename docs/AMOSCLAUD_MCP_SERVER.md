# Amosclaud MCP Server

The Amosclaud MCP server lets Claude, Codex, and any standard Model Context
Protocol client use Amosclaud as a governed software-engineering operator.

It does not simulate repository work. The server calls the real Amosclaud
Autonomous API and returns the resulting pipeline ID, status, jobs, logs, and
verification evidence.

## Exposed tools

- `amosclaud_status` — checks the web service and Autonomous readiness.
- `amosclaud_agent_profile` — reads the live Autonomous mission and scope.
- `inspect_repository` — inspects one repository without applying changes.
- `run_autonomous` — starts build, fix, deploy, monitor, or inspection work.
- `get_pipeline_result` — reads one pipeline result.
- `wait_for_pipeline_result` — waits for a terminal, evidenced result.
- `list_recent_pipelines` — lists recent Autonomous and CI/CD runs.

The server also publishes the `amosclaud://status` resource and an
`autonomous_engineering_task` prompt.

## Install

```bash
python -m pip install -e ".[mcp]"
```

The optional `mcp` extra installs the official MCP Python SDK and the package
installs the `amosclaud-mcp` command. The Railway web runtime does not need this
extra unless the MCP server will run inside that container.

## Required configuration

Create an Amosclaud Autonomous bearer key in the platform and provide it only
through the MCP client's environment:

```bash
export AMOSCLAUD_API_URL="https://www.amosclaud.com"
export AMOSCLAUD_AUTONOMOUS_KEY="replace-with-your-autonomous-key"
amosclaud-mcp
```

Optional:

```bash
export AMOSCLAUD_MCP_TIMEOUT="60"
```

Do not place a real key in a repository, screenshot, issue, or client
configuration that will be shared.

## MCP client configuration

Use a stdio server entry similar to this:

```json
{
  "mcpServers": {
    "amosclaud": {
      "command": "amosclaud-mcp",
      "env": {
        "AMOSCLAUD_API_URL": "https://www.amosclaud.com",
        "AMOSCLAUD_AUTONOMOUS_KEY": "${AMOSCLAUD_AUTONOMOUS_KEY}"
      }
    }
  }
}
```

Some clients do not expand `${...}` values. In that case, launch the client from
a shell where the variable already exists or use the client's encrypted secret
store.

## Proof-first workflow

1. Call `amosclaud_status`.
2. Call `inspect_repository` with the real Amosclaud repository ID.
3. Call `run_autonomous` with one bounded objective.
4. Keep the returned `pipeline_id`.
5. Call `wait_for_pipeline_result`.
6. Treat the work as complete only when the final status, logs, checks, branch,
   commit, and test evidence prove completion.

A green web health check by itself is not proof that Autonomous executed a
repository change.
