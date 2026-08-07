"""Read-only, fail-closed repository scanner for the Amosclaud fixer.

The Scan Bug never edits repository files and never controls the test process. It
walks Git-tracked source text in a deterministic order, records every inspected
line, stops at the first reproducible finding, and produces a redacted SVG code
snapshot plus machine-readable evidence for the autonomous fixer.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

MAX_TEXT_BYTES = 5 * 1024 * 1024
SNAPSHOT_CONTEXT_LINES = 4

SKIP_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".aicode",
    }
)

BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".avi",
        ".bmp",
        ".class",
        ".db",
        ".dll",
        ".doc",
        ".docx",
        ".eot",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jar",
        ".jpeg",
        ".jpg",
        ".lockb",
        ".mp3",
        ".mp4",
        ".otf",
        ".pdf",
        ".png",
        ".pyc",
        ".pyd",
        ".so",
        ".sqlite",
        ".sqlite3",
        ".tar",
        ".ttf",
        ".wav",
        ".webp",
        ".woff",
        ".woff2",
        ".xls",
        ".xlsx",
        ".zip",
    }
)

SHELL_SUFFIXES = frozenset({".sh", ".bash"})
JAVASCRIPT_SUFFIXES = frozenset({".js", ".mjs", ".cjs"})
YAML_SUFFIXES = frozenset({".yaml", ".yml"})
TEST_SKIP_PATTERNS = (
    re.compile(r"@pytest\.mark\.skip(?:\(|\s|$)"),
    re.compile(r"(?<![A-Za-z0-9_])pytest\.skip\s*\("),
    re.compile(r"@unittest\.skip(?:\(|\s|$)"),
)
ALLOW_SKIP_MARKER = "amosclaud: allow-skip"
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")

SECRET_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|private[_-]?key)" r"(\s*[:=]\s*)([^\s,;]+)"
)
BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
GITHUB_TOKEN = re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{8,}")
PRIVATE_KEY_LINE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Finding:
    code: str
    message: str
    path: str
    line: int
    column: int = 1
    severity: str = "error"
    fix_hint: str = "Inspect the captured evidence and apply the smallest safe repair."


@dataclass(slots=True)
class FileCoverage:
    path: str
    lines_scanned: int
    bytes_scanned: int
    sha256: str
    validators: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Exclusion:
    path: str
    reason: str


@dataclass(slots=True)
class ScanReport:
    root: str
    started_at: str
    finished_at: str = ""
    status: str = "running"
    files_scanned: int = 0
    lines_scanned: int = 0
    bytes_scanned: int = 0
    finding: Finding | None = None
    coverage: list[FileCoverage] = field(default_factory=list)
    exclusions: list[Exclusion] = field(default_factory=list)
    snapshot_path: str = ""
    snapshot_sha256: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "files_scanned": self.files_scanned,
            "lines_scanned": self.lines_scanned,
            "bytes_scanned": self.bytes_scanned,
            "finding": asdict(self.finding) if self.finding else None,
            "coverage": [asdict(item) for item in self.coverage],
            "exclusions": [asdict(item) for item in self.exclusions],
            "snapshot_path": self.snapshot_path,
            "snapshot_sha256": self.snapshot_sha256,
        }


def _run_git_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        paths.append(root / raw.decode("utf-8", errors="surrogateescape"))
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def tracked_files(root: Path) -> Iterable[Path]:
    paths = _run_git_files(root)
    if not paths:
        paths = sorted(path for path in root.rglob("*") if path.is_file())
    for path in paths:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in SKIP_PARTS for part in relative.parts):
            continue
        if path.is_file():
            yield path


def _redact(value: str) -> str:
    if PRIVATE_KEY_LINE.search(value):
        return "[REDACTED PRIVATE KEY MATERIAL]"
    value = SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value
    )
    value = BEARER_TOKEN.sub("Bearer [REDACTED]", value)
    return GITHUB_TOKEN.sub("[REDACTED GITHUB TOKEN]", value)


def _snapshot_lines(text: str, line_number: int) -> list[tuple[int, str]]:
    lines = text.splitlines()
    if not lines:
        return [(1, "")]
    safe_line = max(1, min(line_number, len(lines)))
    start = max(1, safe_line - SNAPSHOT_CONTEXT_LINES)
    end = min(len(lines), safe_line + SNAPSHOT_CONTEXT_LINES)
    return [(number, _redact(lines[number - 1])) for number in range(start, end + 1)]


def write_snapshot(path: Path, finding: Finding, text: str) -> str:
    rows = _snapshot_lines(text, finding.line)
    width = 1280
    row_height = 28
    header_height = 116
    height = header_height + (len(rows) * row_height) + 28
    escaped_path = html.escape(f"{finding.path}:{finding.line}:{finding.column}")
    escaped_message = html.escape(finding.message)
    svg_rows = []
    for index, (number, source) in enumerate(rows):
        y = header_height + (index * row_height)
        marker = "▶" if number == finding.line else " "
        rendered = html.escape(source.expandtabs(4))
        svg_rows.append(
            f'<text x="28" y="{y}" font-family="monospace" font-size="17">'
            f"{html.escape(marker)} {number:>6} │ {rendered}</text>"
        )
    svg = "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
            '<rect width="100%" height="100%" rx="16" fill="#111827"/>',
            '<text x="28" y="38" fill="#f9fafb" font-family="sans-serif" '
            'font-size="23" font-weight="700">🐛 Amosclaud Scan Bug caught a finding</text>',
            f'<text x="28" y="72" fill="#93c5fd" font-family="monospace" '
            f'font-size="17">{escaped_path}</text>',
            f'<text x="28" y="98" fill="#fca5a5" font-family="sans-serif" '
            f'font-size="16">{escaped_message}</text>',
            '<g fill="#e5e7eb">',
            *svg_rows,
            "</g>",
            "</svg>",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_finding(path: str, number: int, line: str, *, catch_skips: bool) -> Finding | None:
    if "\x00" in line:
        return Finding("nul-byte", "NUL byte found in tracked text", path, number)
    stripped = line.lstrip()
    if stripped.startswith(CONFLICT_MARKERS):
        return Finding("merge-conflict", "Unresolved merge conflict marker", path, number)
    if line.rstrip(" \t") != line:
        return Finding(
            "trailing-whitespace",
            "Trailing whitespace",
            path,
            number,
            fix_hint="Remove trailing spaces or tabs and rerun verification.",
        )
    if catch_skips and ALLOW_SKIP_MARKER not in line:
        if any(pattern.search(line) for pattern in TEST_SKIP_PATTERNS):
            return Finding(
                "unconditional-test-skip",
                "Unconditional test skip hides test coverage",
                path,
                number,
                fix_hint=(
                    "Repair the test or document an intentional skip on the same line with "
                    f"'{ALLOW_SKIP_MARKER}'."
                ),
            )
    return None


def _syntax_finding(path: Path, relative: str, text: str) -> tuple[Finding | None, list[str]]:
    suffix = path.suffix.lower()
    validators: list[str] = []
    try:
        if suffix == ".py":
            validators.append("python-ast")
            ast.parse(text, filename=relative)
        elif suffix == ".json":
            validators.append("json")
            json.loads(text)
        elif suffix == ".toml":
            validators.append("tomllib")
            tomllib.loads(text)
        elif suffix in YAML_SUFFIXES:
            validators.append("yaml")
            try:
                import yaml  # type: ignore
            except ImportError:
                return (
                    Finding(
                        "coverage-gap",
                        "PyYAML is required to validate tracked YAML",
                        relative,
                        1,
                        fix_hint="Install PyYAML in the Scan Bug workflow.",
                    ),
                    validators,
                )
            yaml.safe_load(text)
        elif suffix in SHELL_SUFFIXES:
            validators.append("bash-n")
            result = subprocess.run(
                ["bash", "-n", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                message = (result.stderr or result.stdout).strip() or "Shell syntax error"
                match = re.search(r"line\s+(\d+)", message)
                line = int(match.group(1)) if match else 1
                return Finding("shell-syntax", message, relative, line), validators
        elif suffix in JAVASCRIPT_SUFFIXES and shutil.which("node"):
            validators.append("node-check")
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                message = (result.stderr or result.stdout).strip() or "JavaScript syntax error"
                match = re.search(rf"{re.escape(str(path))}:(\d+)", message)
                line = int(match.group(1)) if match else 1
                return Finding("javascript-syntax", message, relative, line), validators
    except SyntaxError as exc:
        return (
            Finding("python-syntax", exc.msg, relative, exc.lineno or 1, exc.offset or 1),
            validators,
        )
    except json.JSONDecodeError as exc:
        return Finding("json-syntax", exc.msg, relative, exc.lineno, exc.colno), validators
    except tomllib.TOMLDecodeError as exc:
        line = getattr(exc, "lineno", 1) or 1
        column = getattr(exc, "colno", 1) or 1
        return Finding("toml-syntax", str(exc), relative, line, column), validators
    except Exception as exc:  # YAML libraries use provider-specific exception classes.
        line = 1
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line = int(getattr(mark, "line", 0)) + 1
        return Finding("structured-text-syntax", str(exc), relative, line), validators
    return None, validators


def scan_repository(
    root: Path,
    *,
    snapshot_path: Path,
    catch_test_skips: bool = True,
) -> ScanReport:
    root = root.resolve()
    report = ScanReport(root=str(root), started_at=utc_now())

    for path in tracked_files(root):
        relative = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix in BINARY_SUFFIXES:
            report.exclusions.append(Exclusion(relative, "binary file; no source lines"))
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            finding = Finding("coverage-gap", f"Cannot stat tracked file: {exc}", relative, 1)
            report.finding = finding
            report.status = "caught"
            report.snapshot_sha256 = write_snapshot(snapshot_path, finding, "")
            report.snapshot_path = str(snapshot_path)
            break
        if size > MAX_TEXT_BYTES:
            finding = Finding(
                "coverage-gap",
                f"Tracked text exceeds {MAX_TEXT_BYTES} bytes and was not silently skipped",
                relative,
                1,
                fix_hint="Split, exclude as generated content, or raise the reviewed scan limit.",
            )
            report.finding = finding
            report.status = "caught"
            report.snapshot_sha256 = write_snapshot(snapshot_path, finding, "")
            report.snapshot_path = str(snapshot_path)
            break
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            finding = Finding(
                "invalid-utf8",
                "Tracked non-binary source is not valid UTF-8",
                relative,
                1,
                exc.start + 1,
            )
            report.finding = finding
            report.status = "caught"
            report.snapshot_sha256 = write_snapshot(snapshot_path, finding, "")
            report.snapshot_path = str(snapshot_path)
            break
        except OSError as exc:
            finding = Finding("coverage-gap", f"Cannot read tracked file: {exc}", relative, 1)
            report.finding = finding
            report.status = "caught"
            report.snapshot_sha256 = write_snapshot(snapshot_path, finding, "")
            report.snapshot_path = str(snapshot_path)
            break

        lines = text.splitlines()
        line_total = len(lines)
        if text and not lines:
            line_total = 1
        validators: list[str] = ["line-inspection"]
        caught: Finding | None = None
        for number, line in enumerate(lines, 1):
            report.lines_scanned += 1
            caught = _line_finding(
                relative,
                number,
                line,
                catch_skips=catch_test_skips and "test" in path.name.lower(),
            )
            if caught:
                break
        if not lines and text:
            report.lines_scanned += 1

        scanned_lines = line_total if caught is None else max(1, caught.line)
        digest = hashlib.sha256(raw).hexdigest()
        report.files_scanned += 1
        report.bytes_scanned += len(raw)
        report.coverage.append(FileCoverage(relative, scanned_lines, len(raw), digest, validators))

        if caught is None:
            caught, syntax_validators = _syntax_finding(path, relative, text)
            validators.extend(syntax_validators)
            report.coverage[-1].validators = validators
        if caught:
            report.finding = caught
            report.status = "caught"
            report.snapshot_sha256 = write_snapshot(snapshot_path, caught, text)
            report.snapshot_path = str(snapshot_path)
            break
    else:
        report.status = "complete"

    report.finished_at = utc_now()
    return report


def markdown(report: ScanReport) -> str:
    lines = [
        "# 🐛 Amosclaud Scan Bug",
        "",
        f"- **Status:** `{report.status}`",
        f"- **Files inspected:** `{report.files_scanned}`",
        f"- **Lines inspected:** `{report.lines_scanned}`",
        f"- **Bytes inspected:** `{report.bytes_scanned}`",
        f"- **Excluded binary/generated files:** `{len(report.exclusions)}`",
        "",
    ]
    if report.finding:
        finding = report.finding
        lines.extend(
            [
                "## Catch",
                "",
                f"- **Code:** `{finding.code}`",
                f"- **Location:** `{finding.path}:{finding.line}:{finding.column}`",
                f"- **Reason:** {finding.message}",
                f"- **Fixer instruction:** {finding.fix_hint}",
                f"- **Snapshot:** `{report.snapshot_path}`",
                f"- **Snapshot SHA-256:** `{report.snapshot_sha256}`",
                "",
                "The Scan Bug stopped itself after this catch. Repository tests were not "
                "cancelled, replaced, or marked failed by this scanner.",
            ]
        )
    else:
        lines.extend(
            [
                "## Coverage complete",
                "",
                "Every eligible Git-tracked UTF-8 source line was visited in deterministic "
                "order. Language parsers ran where supported. Repository tests remained "
                "independent from this observer scan.",
            ]
        )
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Read-only Amosclaud repository Scan Bug")
    value.add_argument("root", nargs="?", default=".")
    value.add_argument("--json", dest="json_path", default="scan-bug-report.json")
    value.add_argument("--markdown", dest="markdown_path", default="scan-bug-report.md")
    value.add_argument("--snapshot", default="scan-bug-snapshot.svg")
    value.add_argument("--allow-test-skips", action="store_true")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = Path(args.root).resolve()
    json_path = Path(args.json_path).resolve()
    markdown_path = Path(args.markdown_path).resolve()
    snapshot_path = Path(args.snapshot).resolve()
    report = scan_repository(
        root,
        snapshot_path=snapshot_path,
        catch_test_skips=not args.allow_test_skips,
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    rendered = markdown(report)
    markdown_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 10 if report.status == "caught" else 0


if __name__ == "__main__":
    sys.exit(main())
