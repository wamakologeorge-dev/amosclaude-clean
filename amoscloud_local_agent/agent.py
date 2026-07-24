from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MatrixAgent:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.inbox = root / "inbox"
        self.commands = root / "commands"
        self.results = root / "results"
        self.failed = root / "failed"
        self.state = root / "state"
        self.recovery = root / "recovery"
        self.stop_requested = False
        self.agent_id = os.getenv("AMOS_LOCAL_AGENT_ID") or socket.gethostname()
        self.poll_seconds = float(os.getenv("AMOS_LOCAL_AGENT_POLL_SECONDS", "2"))

    def prepare(self) -> None:
        for directory in (
            self.inbox,
            self.commands,
            self.results,
            self.failed,
            self.state,
            self.recovery,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.write_state("starting")
        self.recover_interrupted_commands()

    def write_state(self, status: str, **extra: Any) -> None:
        payload = {
            "agent_id": self.agent_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        target = self.state / "agent.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(target)

    def recover_interrupted_commands(self) -> None:
        for item in self.recovery.glob("*.json"):
            destination = self.commands / item.name
            if not destination.exists():
                item.replace(destination)

    def claim_command(self, source: Path) -> Path | None:
        claimed = self.recovery / source.name
        try:
            source.replace(claimed)
            return claimed
        except FileNotFoundError:
            return None

    def execute(self, command: dict[str, Any]) -> dict[str, Any]:
        action = str(command.get("action") or "").strip()
        command_id = str(command.get("command_id") or uuid.uuid4())
        if action == "folder.scan":
            relative = str(command.get("target") or "inbox")
            target = (self.root / relative).resolve()
            if self.root.resolve() not in target.parents and target != self.root.resolve():
                raise ValueError("Target escapes the Matrix root")
            target.mkdir(parents=True, exist_ok=True)
            files = [
                {
                    "name": path.name,
                    "path": str(path.relative_to(self.root)),
                    "size": path.stat().st_size,
                    "modified_at": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
                for path in sorted(target.rglob("*"))
                if path.is_file()
            ]
            return {"command_id": command_id, "ok": True, "files": files}
        if action == "agent.ping":
            return {
                "command_id": command_id,
                "ok": True,
                "agent_id": self.agent_id,
                "time": datetime.now(timezone.utc).isoformat(),
            }
        raise ValueError(f"Unsupported action: {action or '<missing>'}")

    def process_once(self) -> int:
        processed = 0
        for source in sorted(self.commands.glob("*.json")):
            claimed = self.claim_command(source)
            if claimed is None:
                continue
            processed += 1
            command_id = claimed.stem
            try:
                command = json.loads(claimed.read_text(encoding="utf-8"))
                result = self.execute(command)
                result.setdefault("command_id", command.get("command_id", command_id))
                result["completed_at"] = datetime.now(timezone.utc).isoformat()
                destination = self.results / f"{result['command_id']}.json"
                destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
                claimed.unlink(missing_ok=True)
            except Exception as exc:
                failure = {
                    "command_id": command_id,
                    "ok": False,
                    "error": str(exc),
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                }
                (self.failed / claimed.name).write_text(
                    json.dumps(failure, indent=2), encoding="utf-8"
                )
                claimed.unlink(missing_ok=True)
        return processed

    def run(self) -> None:
        self.prepare()
        self.write_state("online")
        while not self.stop_requested:
            processed = self.process_once()
            self.write_state("online", processed_last_cycle=processed)
            time.sleep(self.poll_seconds)
        self.write_state("stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Amosclaud Local Matrix Agent")
    parser.add_argument(
        "--matrix-root",
        default=os.getenv("AMOS_MATRIX_ROOT", str(Path.home() / "Amosclaud-Matrix")),
    )
    args = parser.parse_args()
    agent = MatrixAgent(Path(args.matrix_root).expanduser())

    def stop(_signum: int, _frame: object) -> None:
        agent.stop_requested = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    agent.run()


if __name__ == "__main__":
    main()
