# Amosclaud Agent Core

The framework is implemented from scratch in `amoscloud_ai/engineering_agent.py`,
`agent_memory.py`, `provider.py`, and `agent_actions.py`. This boundary owns planning,
constrained tools, durable memory, state, evidence, and verification. It does not own HTTP
authentication or billing.

## Progressive agent memory

Each completed engineering run retrieves relevant lessons, performs the work, records a
sanitized outcome, and rebuilds the current daily learning summary. Memory is stored under
`.amosclaud/memory/` as portable JSONL journals, Markdown daily summaries, and a SQLite FTS5
search index. It is limited by available disk capacity rather than process RAM.

```bash
amosclaud-agent-memory stats
amosclaud-agent-memory recent --limit 20
amosclaud-agent-memory recall "database migration"
amosclaud-agent-memory consolidate
```

Set `AMOSCLAUD_AGENT_MEMORY_HOME` to place memory on a dedicated storage volume. Raw source
files, prompts, and credentials are not copied into learned outcomes; common credential
patterns are redacted before persistence. Back up the memory folder with the workspace data.
