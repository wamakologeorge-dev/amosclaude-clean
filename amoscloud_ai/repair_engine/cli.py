from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from .core import AutonomousRepairEngine, RepairReport


def markdown(report: RepairReport) -> str:
    icon = "🟢" if report.final_verdict.value == "PASS" else "🔴"
    lines = [
        f"# {icon} Amosclaud Autonomous Repair Report",
        "",
        f"- **Repository:** `{report.root}`",
        f"- **Diagnosis:** **{report.diagnosis.value}**",
        f"- **Final result:** **{report.final_verdict.value}**",
        f"- **Repair attempts:** `{report.attempts}`",
        f"- **Changed files:** `{len(report.changed_files)}`",
        "",
        "## What Amosclaud discovered",
        "",
    ]
    if report.findings:
        for item in report.findings:
            location = f" `{item.path}`" if item.path else ""
            if item.line:
                location += f":{item.line}"
            lines.append(
                f"- **{item.severity.value.upper()}** `{item.code}`{location} — {item.message}"
            )
    else:
        lines.append("- No static blockers detected.")
    lines.extend(["", "## Repairs applied", ""])
    if report.repairs:
        for repair in report.repairs:
            mark = "✓" if repair.changed else "–"
            lines.append(f"- {mark} `{repair.path}` — {repair.description}")
    else:
        lines.append("- No repair was applied.")
    lines.extend(["", "## Verification evidence", ""])
    for evidence in report.evidence:
        mark = "✓" if evidence.passed else "✗"
        lines.append(f"- {mark} **{evidence.name}** ({evidence.duration_seconds:.2f}s)")
    lines.extend(
        [
            "",
            "## Truthfulness and safety",
            "",
            "A PASS is emitted only when static diagnosis is healthy and every configured verification command succeeds. Critical findings are never rewritten automatically. Repairs are limited to deterministic low-risk transformations.",
        ]
    )
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Amosclaud Autonomous Repair Engine v1")
    value.add_argument("root", nargs="?", default=".", help="Repository root")
    value.add_argument("--apply", action="store_true", help="Apply deterministic safe repairs")
    value.add_argument("--required", action="append", default=[], help="Required repository file")
    value.add_argument("--verify", action="append", default=[], help="Verification command; repeatable")
    value.add_argument("--max-attempts", type=int, default=2)
    value.add_argument("--json", dest="json_path", help="Write JSON report")
    value.add_argument("--markdown", dest="markdown_path", help="Write Markdown report")
    value.add_argument("--memory", default=".amosclaud/repair-memory.jsonl")
    return value


def main() -> None:
    args = parser().parse_args()
    root = Path(args.root).resolve()
    commands = [shlex.split(command) for command in args.verify]
    memory_path = Path(args.memory)
    if not memory_path.is_absolute():
        memory_path = root / memory_path
    engine = AutonomousRepairEngine(
        root,
        required_files=args.required,
        commands=commands,
        max_attempts=args.max_attempts,
        memory_path=memory_path,
    )
    report = engine.run(apply=args.apply)
    payload = report.as_dict()
    rendered = markdown(report)
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.markdown_path:
        Path(args.markdown_path).write_text(rendered, encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report.final_verdict.value == "PASS" else 1)


if __name__ == "__main__":
    main()
