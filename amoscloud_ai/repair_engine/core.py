from __future__ import annotations

import ast
import json
import re
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable, Sequence


class Severity(StrEnum):
    INFO = "info"
    REPAIRABLE = "repairable"
    CRITICAL = "critical"


class Verdict(StrEnum):
    HEALTHY = "HEALTHY"
    REPAIRABLE = "REPAIRABLE"
    CRITICAL = "CRITICAL"
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(slots=True)
class Finding:
    code: str
    message: str
    severity: Severity
    path: str | None = None
    line: int | None = None
    repair: str | None = None


@dataclass(slots=True)
class Repair:
    code: str
    path: str
    description: str
    changed: bool


@dataclass(slots=True)
class Evidence:
    name: str
    passed: bool
    command: list[str] = field(default_factory=list)
    return_code: int | None = None
    duration_seconds: float = 0.0
    output: str = ""


@dataclass(slots=True)
class RepairReport:
    root: str
    started_at: str
    finished_at: str = ""
    diagnosis: Verdict = Verdict.UNKNOWN
    final_verdict: Verdict = Verdict.UNKNOWN
    attempts: int = 0
    findings: list[Finding] = field(default_factory=list)
    repairs: list[Repair] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "diagnosis": self.diagnosis.value,
            "final_verdict": self.final_verdict.value,
            "attempts": self.attempts,
            "findings": [asdict(item) for item in self.findings],
            "repairs": [asdict(item) for item in self.repairs],
            "evidence": [asdict(item) for item in self.evidence],
            "changed_files": self.changed_files,
        }


KNOWN_ACTION_PINS = {
    "actions/checkout@v4": "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-python@v5": "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
    "actions/cache@v4": "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830",
    "actions/upload-artifact@v4": "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    "actions/download-artifact@v4": "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
}

ACTION_PATTERN = re.compile(r"(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<ref>[^\s#\"']+)")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
LOCAL_ASSET_PATTERN = re.compile(r"(?:src|href)=[\"'](?!https?://|//|#|mailto:)([^\"'?]+)")
TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".json", ".yml", ".yaml", ".sh", ".html", ".css", ".md", ".toml"}
SKIP_PARTS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def iter_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and not any(part in SKIP_PARTS for part in path.parts):
            yield path


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class Doctor:
    def __init__(self, root: Path, required_files: Sequence[str] = ()) -> None:
        self.root = root.resolve()
        self.required_files = tuple(required_files)

    def diagnose(self) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._required_files())
        for path in iter_files(self.root):
            findings.extend(self._basic_text_checks(path))
            if path.suffix == ".py":
                findings.extend(self._python_syntax(path))
            elif path.suffix == ".json":
                findings.extend(self._json_syntax(path))
            elif path.suffix == ".sh":
                findings.extend(self._shell_syntax(path))
            elif path.suffix in {".yml", ".yaml"}:
                findings.extend(self._workflow_checks(path))
            elif path.suffix == ".html":
                findings.extend(self._local_assets(path))
        return findings

    @staticmethod
    def classify(findings: Sequence[Finding]) -> Verdict:
        if any(item.severity == Severity.CRITICAL for item in findings):
            return Verdict.CRITICAL
        if any(item.severity == Severity.REPAIRABLE for item in findings):
            return Verdict.REPAIRABLE
        return Verdict.HEALTHY

    def _required_files(self) -> list[Finding]:
        return [
            Finding("missing-required-file", f"Required file is missing: {name}", Severity.CRITICAL, path=name)
            for name in self.required_files
            if not (self.root / name).is_file()
        ]

    def _basic_text_checks(self, path: Path) -> list[Finding]:
        rel = relative(path, self.root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return [Finding("invalid-utf8", "Text file is not valid UTF-8", Severity.CRITICAL, path=rel)]
        findings: list[Finding] = []
        if not text:
            findings.append(Finding("empty-file", "Changed source/configuration file is empty", Severity.CRITICAL, path=rel))
        for number, line in enumerate(text.splitlines(), 1):
            if line.rstrip() != line:
                findings.append(Finding("trailing-whitespace", "Trailing whitespace", Severity.REPAIRABLE, rel, number, "trim whitespace"))
            if line.startswith("<<<<<<<") or line.startswith("=======") or line.startswith(">>>>>>>"):
                findings.append(Finding("merge-conflict", "Unresolved merge conflict marker", Severity.CRITICAL, rel, number))
        if text and not text.endswith("\n"):
            findings.append(Finding("missing-final-newline", "File has no final newline", Severity.REPAIRABLE, rel, repair="add final newline"))
        return findings

    def _python_syntax(self, path: Path) -> list[Finding]:
        rel = relative(path, self.root)
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            return []
        except SyntaxError as exc:
            return [Finding("python-syntax", exc.msg, Severity.CRITICAL, rel, exc.lineno)]

    def _json_syntax(self, path: Path) -> list[Finding]:
        rel = relative(path, self.root)
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return []
        except json.JSONDecodeError as exc:
            return [Finding("json-syntax", exc.msg, Severity.CRITICAL, rel, exc.lineno)]

    def _shell_syntax(self, path: Path) -> list[Finding]:
        rel = relative(path, self.root)
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return []
        return [Finding("shell-syntax", (result.stderr or result.stdout).strip(), Severity.CRITICAL, rel)]

    def _workflow_checks(self, path: Path) -> list[Finding]:
        rel = relative(path, self.root)
        text = path.read_text(encoding="utf-8")
        findings: list[Finding] = []
        if "\t" in text:
            findings.append(Finding("yaml-tabs", "YAML contains tab indentation", Severity.REPAIRABLE, rel, repair="replace indentation tabs"))
        if path.parent.name == "workflows" and path.parent.parent.name == ".github":
            for number, line in enumerate(text.splitlines(), 1):
                if "uses:" not in line:
                    continue
                match = ACTION_PATTERN.search(line)
                if not match:
                    continue
                ref = match.group("ref")
                action_ref = match.group(0)
                if not FULL_SHA_PATTERN.fullmatch(ref):
                    severity = Severity.REPAIRABLE if action_ref in KNOWN_ACTION_PINS else Severity.CRITICAL
                    repair = KNOWN_ACTION_PINS.get(action_ref)
                    findings.append(Finding("unpinned-action", f"Action is not pinned to a full commit SHA: {action_ref}", severity, rel, number, repair))
        try:
            import yaml  # type: ignore

            yaml.safe_load(text)
        except ImportError:
            if not re.search(r"(?m)^\s*(name|on|jobs):", text):
                findings.append(Finding("yaml-structure", "YAML has no recognizable top-level workflow keys", Severity.CRITICAL, rel))
        except Exception as exc:
            findings.append(Finding("yaml-syntax", str(exc), Severity.CRITICAL, rel))
        return findings

    def _local_assets(self, path: Path) -> list[Finding]:
        rel = relative(path, self.root)
        text = path.read_text(encoding="utf-8")
        findings: list[Finding] = []
        for asset in LOCAL_ASSET_PATTERN.findall(text):
            target = (path.parent / asset).resolve()
            try:
                target.relative_to(self.root)
            except ValueError:
                findings.append(Finding("asset-outside-root", f"Local asset escapes repository root: {asset}", Severity.CRITICAL, rel))
                continue
            if not target.exists():
                findings.append(Finding("missing-local-asset", f"Referenced local asset is missing: {asset}", Severity.CRITICAL, rel))
        return findings


class Fixer:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def apply(self, findings: Sequence[Finding]) -> list[Repair]:
        by_path: dict[str, list[Finding]] = {}
        for finding in findings:
            if finding.path and finding.severity == Severity.REPAIRABLE:
                by_path.setdefault(finding.path, []).append(finding)
        repairs: list[Repair] = []
        for rel, items in by_path.items():
            path = self.root / rel
            if not path.is_file():
                continue
            original = path.read_text(encoding="utf-8")
            updated = original
            codes = {item.code for item in items}
            if "trailing-whitespace" in codes:
                updated = "\n".join(line.rstrip() for line in updated.splitlines())
                if original.endswith("\n"):
                    updated += "\n"
            if "missing-final-newline" in codes and updated and not updated.endswith("\n"):
                updated += "\n"
            if "yaml-tabs" in codes:
                updated = updated.replace("\t", "  ")
            for item in items:
                if item.code == "unpinned-action" and item.repair:
                    line = updated.splitlines()[item.line - 1] if item.line else ""
                    match = ACTION_PATTERN.search(line)
                    if match:
                        updated = updated.replace(match.group(0), item.repair)
            changed = updated != original
            if changed:
                path.write_text(updated, encoding="utf-8")
            repairs.append(Repair("safe-static-repair", rel, ", ".join(sorted(codes)), changed))
        return repairs


class Verifier:
    def __init__(self, root: Path, timeout: int = 300) -> None:
        self.root = root.resolve()
        self.timeout = timeout

    def run(self, commands: Sequence[Sequence[str]]) -> list[Evidence]:
        evidence: list[Evidence] = []
        for command in commands:
            started = time.monotonic()
            try:
                result = subprocess.run(
                    list(command), cwd=self.root, capture_output=True, text=True,
                    timeout=self.timeout, check=False,
                )
                output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
                evidence.append(Evidence(" ".join(shlex.quote(part) for part in command), result.returncode == 0, list(command), result.returncode, time.monotonic() - started, output[-12000:]))
            except (OSError, subprocess.TimeoutExpired) as exc:
                evidence.append(Evidence(" ".join(command), False, list(command), None, time.monotonic() - started, str(exc)))
        return evidence


class RepairMemory:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, report: RepairReport) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report.as_dict(), sort_keys=True) + "\n")


class AutonomousRepairEngine:
    def __init__(
        self,
        root: Path,
        *,
        required_files: Sequence[str] = (),
        commands: Sequence[Sequence[str]] = (),
        max_attempts: int = 2,
        memory_path: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.doctor = Doctor(self.root, required_files)
        self.fixer = Fixer(self.root)
        self.verifier = Verifier(self.root)
        self.commands = list(commands)
        self.max_attempts = max(1, max_attempts)
        self.memory = RepairMemory(memory_path or self.root / ".amosclaud" / "repair-memory.jsonl")

    def run(self, apply: bool = False) -> RepairReport:
        report = RepairReport(root=str(self.root), started_at=utc_now())
        initial = self.doctor.diagnose()
        report.findings = initial
        report.diagnosis = self.doctor.classify(initial)
        if apply:
            for attempt in range(1, self.max_attempts + 1):
                report.attempts = attempt
                repairable = [item for item in report.findings if item.severity == Severity.REPAIRABLE]
                if not repairable:
                    break
                repairs = self.fixer.apply(repairable)
                report.repairs.extend(repairs)
                report.changed_files = sorted({item.path for item in report.repairs if item.changed})
                report.findings = self.doctor.diagnose()
                if not any(item.severity == Severity.REPAIRABLE for item in report.findings):
                    break
        static_verdict = self.doctor.classify(report.findings)
        static_ok = static_verdict == Verdict.HEALTHY
        report.evidence.append(Evidence("Amosclaud Doctor static diagnosis", static_ok, output=static_verdict.value))
        if static_ok and self.commands:
            report.evidence.extend(self.verifier.run(self.commands))
        if any(not item.passed for item in report.evidence):
            report.final_verdict = Verdict.FAIL
        elif report.evidence:
            report.final_verdict = Verdict.PASS
        else:
            report.final_verdict = Verdict.UNKNOWN
        report.finished_at = utc_now()
        self.memory.record(report)
        return report
