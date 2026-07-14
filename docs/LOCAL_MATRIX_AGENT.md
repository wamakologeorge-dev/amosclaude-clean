# Amosclaud Local Matrix Agent

The Local Matrix Agent is a durable process that continues handling local commands when Amosclaud.com is unavailable.

## Matrix layout

By default the agent creates `~/Amosclaud-Matrix` with:

- `commands/` — JSON commands waiting to run
- `recovery/` — commands claimed by the agent while executing
- `results/` — successful command results
- `failed/` — failed command reports
- `inbox/` — local files available to Matrix workflows
- `state/agent.json` — atomic heartbeat and current state

## Run

```bash
python -m amoscloud_local_agent.agent
```

Custom location:

```bash
python -m amoscloud_local_agent.agent --matrix-root /path/to/Amosclaud-Matrix
```

## First commands

Create `commands/ping.json`:

```json
{
  "command_id": "ping-1",
  "action": "agent.ping"
}
```

Create `commands/scan.json`:

```json
{
  "command_id": "scan-1",
  "action": "folder.scan",
  "target": "inbox"
}
```

The agent writes results to `results/` and uses atomic file moves so interrupted work is recovered after restart.

## Security boundary

This first milestone intentionally supports only allow-listed local actions. It does not execute arbitrary shell commands and does not bypass carrier, SIM, router, or operating-system security.

## Next milestone

- signed pairing with Amosclaud.com
- outbound command/result synchronization
- Windows, Linux, and macOS service installers
- operating-system hotspot adapters
- encrypted local secrets
