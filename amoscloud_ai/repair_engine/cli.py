from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from .core import RepairReport
from .decision_engine import AutonomousDecisionEngine, objective_from_environment
from .failure_strategy import apply_ci_failure_strategy


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
    lines.extend(["", "## Decision and verification evidence", ""])
    for evidence in report.evidence:
        mark = "✓" if evidence.passed else "✗"
        lines.append(f"- {mark} **{evidence.name}** ({evidence.duration_seconds:.2f}s)")
        if evidence.output:
            summary = evidence.output.replace("\n", " ")[:500]
            lines.append(f"  - `{summary}`")
    lines.extend(
        [
            "",
            "## Truthfulness and safety",
            "",
            "A PASS is emitted only when the selected repair is healthy under Doctor verification and every configured verification command succeeds. Objective-named files are prioritized over unrelated findings. Failed attempts are rolled back, critical findings are never rewritten automatically, and only deterministic low-risk transformations may be published.",
        ]
    )
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Amosclaud Autonomous Decision and Self-Healing Engine")
    value.add_argument("root", nargs="?", default=".", help="Repository root")
    value.add_argument("--apply", action="store_true", help="Apply deterministic safe repairs")
    value.add_argument("--objective", default="", help="Human objective or CI failure evidence used to prioritize repairs")
    value.add_argument("--failure-log", help="Path to a captured CI failure log")
    value.add_argument("--required", action="append", default=[], help="Required repository file")
    value.add_argument("--verify", action="append", default=[], help="Verification command; repeatable")
    value.add_argument("--max-attempts", type=int, default=3)
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
    objective = args.objective.strip() or objective_from_environment()
    failure_evidence = objective
    if args.failure_log:
        log_path = Path(args.failure_log)
        if log_path.is_file():
            failure_evidence = objective + "\n" + log_path.read_text(encoding="utf-8", errors="replace")

    evidence_repairs = apply_ci_failure_strategy(root, failure_evidence) if args.apply else []
    engine = AutonomousDecisionEngine(
        root,
        objective=objective,
        required_files=args.required,
        commands=commands,
        max_attempts=args.max_attempts,
        memory_path=memory_path,
    )
    report = engine.run(apply=args.apply)
    if evidence_repairs:
        report.repairs = evidence_repairs + report.repairs
        repaired_paths = [repair.path for repair in evidence_repairs if repair.changed]
        report.changed_files = sorted(set(report.changed_files + repaired_paths))
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
