"""Evidence-backed repository scanner and deterministic fixer handoff."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tomllib
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from amoscloud_ai.repair_engine.core import (
    ACTION_PATTERN,
    FULL_SHA_PATTERN,
    KNOWN_ACTION_PINS,
    Fixer,
    Finding,
    Severity,
    Verifier,
)

SCAN_SCHEMA = "amosclaud.repository-scan.v1"
MAX_SOURCE_BYTES = 2_000_000
SOURCE_SUFFIXES = {
    ".bash",
    ".c",
    ".cc",
    ".cfg",
    ".cjs",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".mjs",
    ".php",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
SPECIAL_SOURCE_NAMES = {
    "dockerfile",
    "gemfile",
    "jenkinsfile",
    "makefile",
    "procfile",
    "rakefile",
}
SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "node_modules",
    "target",
    "vendor",
    "venv",
}
SENSITIVE_EXACT_NAMES = {
    ".env",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
SENSITIVE_DIRECTORIES = {".secrets", "credentials", "private-keys", "secrets"}
LOCAL_ASSET_PATTERN = re.compile(
    r"""(?:src|href)=["'](?!https?://|//|#|mailto:|data:)([^"'?]+)"""
)
STRONG_SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
REDACTION_PATTERN = re.compile(
    r"""(?ix)
    (?P<name>password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)
    (?P<sep>\s*[:=]\s*)(?P<quote>["'])(?P<value>[^"'\n]+)(?P=quote)
    """
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable_findings(findings: Sequence[Finding]) -> list[dict[str, object]]:
    return [asdict(item) for item in findings]


def is_source(path: Path) -> bool:
    return (
        path.name.lower() in SPECIAL_SOURCE_NAMES
        or path.suffix.lower() in SOURCE_SUFFIXES
    )


def is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in SENSITIVE_EXACT_NAMES
        or name.startswith(".env.")
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or any(part.lower() in SENSITIVE_DIRECTORIES for part in path.parts)
    )


def redact(text: str) -> str:
    text = REDACTION_PATTERN.sub(
        lambda match: (
            f"{match.group('name')}{match.group('sep')}"
            f"{match.group('quote')}[REDACTED]{match.group('quote')}"
        ),
        text,
    )
    text = re.sub(r"\bAKIA[0-9A-Z]{16}\b", "[REDACTED AWS KEY]", text)
    text = re.sub(
        r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b",
        "[REDACTED GITHUB TOKEN]",
        text,
    )
    if "PRIVATE KEY-----" in text:
        return "[REDACTED PRIVATE KEY MATERIAL]"
    return text


class RepositoryScanner:
    """Inspect every UTF-8 line in the declared non-sensitive source scope."""

    def __init__(
        self,
        root: Path,
        *,
        maximum_bytes: int = MAX_SOURCE_BYTES,
        context_lines: int = 2,
    ) -> None:
        self.root = root.expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("repository root must be a directory")
        if maximum_bytes < 1:
            raise ValueError("maximum_bytes must be positive")
        if context_lines < 0 or context_lines > 20:
            raise ValueError("context_lines must be between 0 and 20")
        self.maximum_bytes = maximum_bytes
        self.context_lines = context_lines

    def _walk(self) -> Iterable[Path]:
        for directory, names, files in os.walk(self.root):
            base = Path(directory)
            relative_directory = base.relative_to(self.root)
            if relative_directory.parts[:2] == (".amosclaud", "full-scan"):
                names[:] = []
                continue
            names[:] = sorted(
                name for name in names if name not in SKIP_DIRECTORIES
            )
            for name in sorted(files):
                yield base / name

    def _snapshot(
        self,
        path: Path,
        source: str,
        digest: str,
        finding: Finding,
    ) -> dict[str, object]:
        lines = source.splitlines()
        if not lines:
            return {
                "path": finding.path,
                "finding_code": finding.code,
                "focus_line": finding.line,
                "start_line": 0,
                "end_line": 0,
                "source_sha256": digest,
                "text": "",
            }
        focus = max(0, min((finding.line or 1) - 1, len(lines) - 1))
        start = max(0, focus - self.context_lines)
        end = min(len(lines), focus + self.context_lines + 1)
        rendered = "\n".join(
            f"{index + 1:>6} | {redact(lines[index])}"
            for index in range(start, end)
        )
        return {
            "path": path.relative_to(self.root).as_posix(),
            "finding_code": finding.code,
            "focus_line": finding.line,
            "start_line": start + 1,
            "end_line": end,
            "source_sha256": digest,
            "text": rendered,
        }

    @staticmethod
    def _basic(path: str, source: str) -> list[Finding]:
        findings: list[Finding] = []
        if "\x00" in source:
            findings.append(
                Finding(
                    "nul-byte",
                    "Source contains a NUL byte",
                    Severity.CRITICAL,
                    path,
                )
            )
        for number, line in enumerate(source.splitlines(), 1):
            if line.rstrip() != line:
                findings.append(
                    Finding(
                        "trailing-whitespace",
                        "Trailing whitespace",
                        Severity.REPAIRABLE,
                        path,
                        number,
                        "trim whitespace",
                    )
                )
            if line.startswith(("<<<<<<<", "=======", ">>>>>>>")):
                findings.append(
                    Finding(
                        "merge-conflict",
                        "Unresolved merge conflict marker",
                        Severity.CRITICAL,
                        path,
                        number,
                    )
                )
            if any(pattern.search(line) for pattern in STRONG_SECRET_PATTERNS):
                findings.append(
                    Finding(
                        "hardcoded-secret",
                        "Strong credential or private-key signature found",
                        Severity.CRITICAL,
                        path,
                        number,
                    )
                )
        if source and not source.endswith("\n"):
            findings.append(
                Finding(
                    "missing-final-newline",
                    "File has no final newline",
                    Severity.REPAIRABLE,
                    path,
                    repair="add final newline",
                )
            )
        return findings

    @staticmethod
    def _python(path: str, source: str) -> list[Finding]:
        try:
            ast.parse(source, filename=path)
            return []
        except SyntaxError as exc:
            return [
                Finding(
                    "python-syntax",
                    exc.msg,
                    Severity.CRITICAL,
                    path,
                    exc.lineno,
                )
            ]

    @staticmethod
    def _json(path: str, source: str) -> list[Finding]:
        try:
            json.loads(source)
            return []
        except json.JSONDecodeError as exc:
            return [
                Finding(
                    "json-syntax",
                    exc.msg,
                    Severity.CRITICAL,
                    path,
                    exc.lineno,
                )
            ]

    @staticmethod
    def _toml(path: str, source: str) -> list[Finding]:
        try:
            tomllib.loads(source)
            return []
        except tomllib.TOMLDecodeError as exc:
            return [
                Finding(
                    "toml-syntax",
                    str(exc),
                    Severity.CRITICAL,
                    path,
                )
            ]

    @staticmethod
    def _yaml(file_path: Path, path: str, source: str) -> list[Finding]:
        findings: list[Finding] = []
        if "\t" in source:
            findings.append(
                Finding(
                    "yaml-tabs",
                    "YAML contains tab indentation",
                    Severity.REPAIRABLE,
                    path,
                    repair="replace indentation tabs",
                )
            )
        try:
            import yaml

            yaml.safe_load(source)
        except ImportError:
            pass
        except Exception as exc:
            mark = getattr(exc, "problem_mark", None)
            line = int(mark.line) + 1 if mark is not None else None
            findings.append(
                Finding(
                    "yaml-syntax",
                    str(exc),
                    Severity.CRITICAL,
                    path,
                    line,
                )
            )
        if (
            file_path.parent.name == "workflows"
            and file_path.parent.parent.name == ".github"
        ):
            for number, line in enumerate(source.splitlines(), 1):
                match = ACTION_PATTERN.search(line) if "uses:" in line else None
                if not match or FULL_SHA_PATTERN.fullmatch(match.group("ref")):
                    continue
                action_ref = match.group(0)
                repair = KNOWN_ACTION_PINS.get(action_ref)
                findings.append(
                    Finding(
                        "unpinned-action",
                        f"Action is not pinned to a full commit SHA: {action_ref}",
                        Severity.REPAIRABLE if repair else Severity.CRITICAL,
                        path,
                        number,
                        repair,
                    )
                )
        return findings

    def _html(self, file_path: Path, path: str, source: str) -> list[Finding]:
        findings: list[Finding] = []
        for asset in LOCAL_ASSET_PATTERN.findall(source):
            target = (file_path.parent / asset).resolve()
            try:
                target.relative_to(self.root)
            except ValueError:
                findings.append(
                    Finding(
                        "asset-outside-root",
                        f"Local asset escapes repository root: {asset}",
                        Severity.CRITICAL,
                        path,
                    )
                )
                continue
            if not target.exists():
                findings.append(
                    Finding(
                        "missing-local-asset",
                        f"Referenced local asset is missing: {asset}",
                        Severity.CRITICAL,
                        path,
                    )
                )
        return findings

    @staticmethod
    def _external_syntax(
        executable: str,
        arguments: Sequence[str],
        code: str,
        path: str,
    ) -> tuple[list[Finding], str | None]:
        if not shutil.which(executable):
            return [], executable
        try:
            result = subprocess.run(
                [executable, *arguments],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [
                Finding(
                    f"{code}-check-failed",
                    str(exc),
                    Severity.CRITICAL,
                    path,
                )
            ], None
        if result.returncode == 0:
            return [], None
        message = (result.stderr or result.stdout or "syntax check failed").strip()
        return [
            Finding(
                code,
                redact(message[-2_000:]),
                Severity.CRITICAL,
                path,
            )
        ], None

    def _language_checks(
        self,
        file_path: Path,
        path: str,
        source: str,
    ) -> tuple[list[Finding], list[str]]:
        suffix = file_path.suffix.lower()
        unavailable: list[str] = []
        if suffix == ".py":
            return self._python(path, source), unavailable
        if suffix == ".json":
            return self._json(path, source), unavailable
        if suffix == ".toml":
            return self._toml(path, source), unavailable
        if suffix in {".yaml", ".yml"}:
            return self._yaml(file_path, path, source), unavailable
        if suffix == ".html":
            return self._html(file_path, path, source), unavailable
        if suffix in {".sh", ".bash"}:
            found, missing = self._external_syntax(
                "bash",
                ["-n", str(file_path)],
                "shell-syntax",
                path,
            )
        elif suffix in {".js", ".mjs", ".cjs"}:
            found, missing = self._external_syntax(
                "node",
                ["--check", str(file_path)],
                "javascript-syntax",
                path,
            )
        else:
            return [], unavailable
        if missing:
            unavailable.append(missing)
        return found, unavailable

    def scan_once(self) -> dict[str, object]:
        coverage = {
            "discovered_files": 0,
            "non_source_files": 0,
            "eligible_files": 0,
            "scanned_files": 0,
            "scanned_lines": 0,
            "scanned_bytes": 0,
            "policy_skipped": [],
            "errors": [],
            "analyzers_unavailable": [],
            "files": [],
        }
        findings: list[Finding] = []
        snapshots: list[dict[str, object]] = []

        for file_path in self._walk():
            coverage["discovered_files"] += 1
            if not is_source(file_path):
                coverage["non_source_files"] += 1
                continue

            coverage["eligible_files"] += 1
            relative_path = file_path.relative_to(self.root)
            path = relative_path.as_posix()
            if file_path.is_symlink() or is_sensitive(relative_path):
                item = {
                    "path": path,
                    "status": "policy_skipped",
                    "reason": (
                        "symbolic links are not followed"
                        if file_path.is_symlink()
                        else "protected credential or secret path"
                    ),
                }
                coverage["policy_skipped"].append(item)
                coverage["files"].append(item)
                continue
            try:
                size = file_path.stat().st_size
                if size > self.maximum_bytes:
                    raise ValueError(
                        f"source exceeds maximum_bytes={self.maximum_bytes}"
                    )
                raw = file_path.read_bytes()
                source = raw.decode("utf-8")
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                item = {"path": path, "status": "error", "reason": str(exc)}
                coverage["errors"].append(item)
                coverage["files"].append(item)
                continue

            digest = hashlib.sha256(raw).hexdigest()
            lines = len(source.splitlines())
            item = {
                "path": path,
                "status": "scanned",
                "language": (
                    file_path.suffix.lower().lstrip(".")
                    or file_path.name.lower()
                ),
                "bytes_scanned": len(raw),
                "lines_scanned": lines,
                "sha256": digest,
            }
            coverage["files"].append(item)
            coverage["scanned_files"] += 1
            coverage["scanned_lines"] += lines
            coverage["scanned_bytes"] += len(raw)

            file_findings = self._basic(path, source)
            language_findings, unavailable = self._language_checks(
                file_path,
                path,
                source,
            )
            file_findings.extend(language_findings)
            coverage["analyzers_unavailable"].extend(unavailable)
            for finding in file_findings:
                findings.append(finding)
                snapshots.append(
                    self._snapshot(file_path, source, digest, finding)
                )

        coverage["analyzers_unavailable"] = sorted(
            set(coverage["analyzers_unavailable"])
        )
        return {
            "coverage": coverage,
            "findings": findings,
            "snapshots": snapshots,
        }


def fixer_handoff(
    findings: Sequence[Finding],
    snapshots: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    snapshot_index = {
        (item["path"], item["finding_code"], item["focus_line"]): item
        for item in snapshots
    }
    handoff = []
    for finding in findings:
        snapshot = snapshot_index.get(
            (finding.path or "", finding.code, finding.line),
            {
                "path": finding.path or "<verification>",
                "finding_code": finding.code,
                "focus_line": finding.line,
                "start_line": 0,
                "end_line": 0,
                "source_sha256": "",
                "text": redact(finding.message)[:2_000],
            },
        )
        material = (
            f"{snapshot['path']}:{finding.line}:{finding.code}:"
            f"{snapshot['source_sha256']}"
        ).encode()
        handoff.append(
            {
                "handoff_id": (
                    "fix_" + hashlib.sha256(material).hexdigest()[:20]
                ),
                "finding": asdict(finding),
                "source_sha256": snapshot["source_sha256"],
                "snapshot": snapshot,
                "action": (
                    "apply_deterministic_fixer"
                    if finding.severity == Severity.REPAIRABLE
                    else "agent_or_developer_fix_required"
                ),
                "status": "queued",
            }
        )
    return handoff


def run_scan(
    root: Path,
    *,
    send_to_fixer: bool = False,
    maximum_bytes: int = MAX_SOURCE_BYTES,
    context_lines: int = 2,
    verification_commands: Sequence[Sequence[str]] = (),
    verification_timeout: int = 300,
) -> dict[str, object]:
    started_at = utc_now()
    scanner = RepositoryScanner(
        root,
        maximum_bytes=maximum_bytes,
        context_lines=context_lines,
    )
    initial = scanner.scan_once()
    repairs = []
    if send_to_fixer and initial["findings"]:
        repairs = Fixer(scanner.root).apply(initial["findings"])
        final = scanner.scan_once()
    else:
        final = initial

    verification = []
    verification_findings: list[Finding] = []
    if verification_commands:
        verification = Verifier(
            scanner.root,
            timeout=verification_timeout,
        ).run(verification_commands)
        for evidence in verification:
            if not evidence.passed:
                verification_findings.append(
                    Finding(
                        "verification-failure",
                        f"{evidence.name}: {redact(evidence.output[-2_000:])}",
                        Severity.CRITICAL,
                    )
                )

    remaining = [*final["findings"], *verification_findings]
    snapshots = list(final["snapshots"])
    for finding in verification_findings:
        snapshots.append(
            {
                "path": "<verification>",
                "finding_code": finding.code,
                "focus_line": None,
                "start_line": 0,
                "end_line": 0,
                "source_sha256": "",
                "text": finding.message,
            }
        )

    coverage = final["coverage"]
    coverage_complete = (
        not coverage["errors"]
        and not coverage["analyzers_unavailable"]
    )
    verdict = (
        "INCOMPLETE"
        if not coverage_complete
        else ("FAIL" if remaining else "PASS")
    )
    return {
        "schema": SCAN_SCHEMA,
        "root": str(scanner.root),
        "started_at": started_at,
        "finished_at": utc_now(),
        "coverage_scope": (
            "Every UTF-8 line in every non-sensitive source/configuration "
            "file under the repository root, excluding dependency, cache, "
            "generated, build, and protected credential paths."
        ),
        "coverage": {**coverage, "complete": coverage_complete},
        "initial_findings": _jsonable_findings(initial["findings"]),
        "remaining_findings": _jsonable_findings(remaining),
        "snapshots": snapshots,
        "fixer_handoff": fixer_handoff(remaining, snapshots),
        "repairs": [asdict(item) for item in repairs],
        "verification": [asdict(item) for item in verification],
        "verdict": verdict,
    }


def markdown(report: dict[str, object]) -> str:
    coverage = report["coverage"]
    handoff = report["fixer_handoff"]
    repairs = report["repairs"]
    lines = [
        "# Amosclaud Full Repository Scan",
        "",
        f"- **Verdict:** **{report['verdict']}**",
        (
            "- **Coverage complete:** **"
            f"{'yes' if coverage['complete'] else 'no'}**"
        ),
        f"- **Files discovered:** `{coverage['discovered_files']}`",
        f"- **Eligible source/config files:** `{coverage['eligible_files']}`",
        f"- **Files scanned:** `{coverage['scanned_files']}`",
        f"- **Lines scanned:** `{coverage['scanned_lines']}`",
        f"- **Initial findings:** `{len(report['initial_findings'])}`",
        f"- **Remaining findings:** `{len(report['remaining_findings'])}`",
        (
            "- **Safe repairs changed:** `"
            f"{sum(1 for item in repairs if item['changed'])}`"
        ),
        "",
        "## Coverage contract",
        "",
        str(report["coverage_scope"]),
        "",
    ]
    if coverage["policy_skipped"]:
        lines.extend(["## Protected paths not read", ""])
        lines.extend(
            f"- `{item['path']}` — {item['reason']}"
            for item in coverage["policy_skipped"]
        )
        lines.append("")
    if coverage["errors"]:
        lines.extend(["## Coverage errors", ""])
        lines.extend(
            f"- `{item['path']}` — {item['reason']}"
            for item in coverage["errors"]
        )
        lines.append("")
    if coverage["analyzers_unavailable"]:
        lines.extend(["## Required analyzers unavailable", ""])
        lines.append(
            "- "
            + ", ".join(
                f"`{name}`" for name in coverage["analyzers_unavailable"]
            )
        )
        lines.append("")
    lines.extend(["## Remaining findings sent to the fixer", ""])
    if not handoff:
        lines.append("- None.")
    for item in handoff:
        finding = item["finding"]
        location = finding.get("path") or "<verification>"
        if finding.get("line"):
            location = f"{location}:{finding['line']}"
        lines.append(
            f"- **{str(finding['severity']).upper()}** "
            f"`{finding['code']}` `{location}` — {finding['message']}"
        )
        if item["snapshot"]["text"]:
            lines.extend(
                [
                    "",
                    "```text",
                    str(item["snapshot"]["text"]),
                    "```",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## Truthfulness rule",
            "",
            "PASS means every file in the declared coverage scope was read, "
            "all required analyzers were available, no finding remains after "
            "deterministic fixing, and every requested verification command "
            "passed. Starting the scanner or fixer is never reported as proof "
            "that the repository is healthy.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _git_patch(root: Path) -> str:
    if not shutil.which("git") or not (root / ".git").exists():
        return ""
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--binary"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Scan every non-sensitive source line, capture evidence, and "
            "route findings to the Amosclaud fixer."
        )
    )
    value.add_argument("root", nargs="?", default=".")
    value.add_argument(
        "--send-to-fixer",
        action="store_true",
        help="Apply deterministic low-risk repairs and then rescan",
    )
    value.add_argument("--output", default=".amosclaud/full-scan")
    value.add_argument("--verify", action="append", default=[])
    value.add_argument("--maximum-bytes", type=int, default=MAX_SOURCE_BYTES)
    value.add_argument("--context-lines", type=int, default=2)
    value.add_argument("--verification-timeout", type=int, default=300)
    return value


def main() -> None:
    args = parser().parse_args()
    root = Path(args.root).expanduser().resolve()
    report = run_scan(
        root,
        send_to_fixer=args.send_to_fixer,
        maximum_bytes=args.maximum_bytes,
        context_lines=args.context_lines,
        verification_commands=[
            shlex.split(command) for command in args.verify
        ],
        verification_timeout=args.verification_timeout,
    )
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.mkdir(parents=True, exist_ok=True)
    rendered = markdown(report)
    (output / "scan-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "scan-report.md").write_text(rendered, encoding="utf-8")
    (output / "fixer-handoff.json").write_text(
        json.dumps(
            report["fixer_handoff"],
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "fixer.patch").write_text(
        _git_patch(root),
        encoding="utf-8",
    )
    print(rendered)
    raise SystemExit(0 if report["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
