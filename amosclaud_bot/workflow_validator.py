"""Amosclaud-native GitHub Actions workflow validator.

AMOSCLAUD-TOOL-SOVEREIGNTY-POLICY:v1

Amosclaud owns this check. It is a first-party replacement for external
workflow linters, and it detects the class of defect that GitHub rejects when
it loads a workflow file -- the failures that produce a run with zero jobs and
no annotations, which no test suite and no local YAML parse can see.

Every rule below was derived from a real rejection observed on this
repository, so the validator is grounded in GitHub's own verdicts rather than
in a general style opinion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml

WORKFLOW_DIRECTORY = ".github/workflows"
WORKFLOW_SUFFIXES = (".yml", ".yaml")

# Contexts GitHub recognises. Anything outside this set is treated as a
# function call or literal and is deliberately ignored, which keeps the
# validator free of false positives on valid files.
KNOWN_CONTEXTS = frozenset(
    {
        "github",
        "env",
        "vars",
        "job",
        "jobs",
        "steps",
        "runner",
        "secrets",
        "strategy",
        "matrix",
        "needs",
        "inputs",
    }
)

# Where each context may legally appear. GitHub evaluates workflow-level and
# job-level keys before a runner exists, so runner/steps/job are unavailable
# there no matter how reasonable the expression looks.
WORKFLOW_ENV_CONTEXTS = frozenset({"github", "inputs", "vars"})
JOB_ENV_CONTEXTS = frozenset({"github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"})
JOB_IF_CONTEXTS = frozenset({"github", "needs", "vars", "inputs"})

_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_CONTEXT_ROOT = re.compile(r"(?<![\w.'\"-])([a-zA-Z_][a-zA-Z0-9_-]*)\s*(?=[.\[])")

# Top-level keys that prove a file is not a workflow at all. These files sit in
# the workflows directory and GitHub tries, and fails, to run them.
FOREIGN_TOP_LEVEL_KEYS = {
    "channels": "conda environment file",
    "dependencies": "conda environment file",
    "services": "Render/Compose service file",
    "databases": "Render service file",
    "version": "Compose or CI service file",
}


@dataclass(frozen=True)
class Finding:
    """A single workflow defect."""

    path: str
    line: int
    code: str
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


def _line_of(node: Any, default: int = 1) -> int:
    mark = getattr(node, "start_mark", None)
    return (mark.line + 1) if mark is not None else default


def _mapping_items(node: Any) -> Iterator[tuple[Any, Any]]:
    if isinstance(node, yaml.MappingNode):
        yield from node.value


def _get(node: Any, *names: str) -> Any:
    """Return the value node for the first matching key.

    ``on`` is parsed as the boolean ``True`` under YAML 1.1, so callers pass
    every spelling a key may take.
    """

    wanted = {name.lower() for name in names}
    for key, value in _mapping_items(node):
        raw = getattr(key, "value", "")
        text = str(raw).lower()
        if text in wanted or (True in {raw} and "on" in wanted):
            return value
        if text in {"true", "yes"} and "on" in wanted:
            return value
    return None


def _scalar(node: Any) -> str:
    return str(getattr(node, "value", "") or "")


def _sequence(node: Any) -> list[Any]:
    return list(node.value) if isinstance(node, yaml.SequenceNode) else []


def contexts_in(expression: str) -> set[str]:
    """Return the context roots referenced inside an expression string."""

    found: set[str] = set()
    for body in _EXPRESSION.findall(expression):
        for match in _CONTEXT_ROOT.finditer(body):
            name = match.group(1)
            if name in KNOWN_CONTEXTS:
                found.add(name)
    return found


def _check_expression_scope(
    node: Any,
    allowed: Iterable[str],
    path: str,
    location: str,
    findings: list[Finding],
) -> None:
    permitted = set(allowed)
    for used in sorted(contexts_in(_scalar(node))):
        if used not in permitted:
            findings.append(
                Finding(
                    path=path,
                    line=_line_of(node),
                    code="AWV004",
                    message=(
                        f"the '{used}' context is not available in {location}; "
                        f"GitHub rejects the whole file with "
                        f"\"Unrecognized named-value: '{used}'\""
                    ),
                )
            )


def _check_env_block(
    env_node: Any,
    allowed: Iterable[str],
    path: str,
    location: str,
    findings: list[Finding],
) -> None:
    for _key, value in _mapping_items(env_node):
        _check_expression_scope(value, allowed, path, location, findings)


def _self_listening_triggers(root: Any, path: str, findings: list[Finding]) -> None:
    name_node = _get(root, "name")
    if name_node is None:
        return
    own_name = _scalar(name_node).strip()
    if not own_name:
        return
    triggers = _get(root, "on")
    workflow_run = _get(triggers, "workflow_run") if triggers is not None else None
    if workflow_run is None:
        return
    listed = _get(workflow_run, "workflows")
    for item in _sequence(listed):
        if _scalar(item).strip() == own_name:
            findings.append(
                Finding(
                    path=path,
                    line=_line_of(item),
                    code="AWV003",
                    message=(
                        f"workflow {own_name!r} lists itself in its own "
                        f"workflow_run trigger; GitHub refuses the file with "
                        f'"cannot listen to itself" and never schedules a job'
                    ),
                )
            )


def local_called_workflows(root: Any) -> set[str]:
    """Return local reusable workflows this file calls."""

    called: set[str] = set()
    jobs = _get(root, "jobs")
    for _job_id, job in _mapping_items(jobs):
        uses = _get(job, "uses")
        if uses is None:
            continue
        target = _scalar(uses).strip()
        if target.startswith("./"):
            called.add(target.removeprefix("./").split("@")[0])
    return called


def validate_text(text: str, path: str) -> list[Finding]:
    """Validate one workflow document."""

    findings: list[Finding] = []
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = (mark.line + 1) if mark is not None else 1
        problem = getattr(error, "problem", None) or "invalid YAML"
        return [Finding(path, line, "AWV001", f"YAML syntax error: {problem}")]

    if not isinstance(root, yaml.MappingNode):
        return [Finding(path, 1, "AWV002", "workflow must be a mapping at the top level")]

    top_level = {str(getattr(key, "value", "")).lower() for key, _ in _mapping_items(root)}
    foreign = sorted(top_level & set(FOREIGN_TOP_LEVEL_KEYS))
    jobs_node = _get(root, "jobs")

    if jobs_node is None:
        kind = FOREIGN_TOP_LEVEL_KEYS[foreign[0]] if foreign else "not a workflow"
        return [
            Finding(
                path,
                1,
                "AWV002",
                (
                    f"no 'jobs:' key, so GitHub cannot run this file ({kind}). "
                    f"Move it out of {WORKFLOW_DIRECTORY}/"
                ),
            )
        ]

    if _get(root, "on") is None:
        findings.append(
            Finding(path, 1, "AWV006", "no 'on:' trigger, so the workflow can never run")
        )

    _self_listening_triggers(root, path, findings)
    _check_env_block(
        _get(root, "env"), WORKFLOW_ENV_CONTEXTS, path, "workflow-level env:", findings
    )

    for _job_id, job in _mapping_items(jobs_node):
        _check_env_block(_get(job, "env"), JOB_ENV_CONTEXTS, path, "job-level env:", findings)
        condition = _get(job, "if")
        if condition is not None:
            _check_expression_scope(condition, JOB_IF_CONTEXTS, path, "a job-level if:", findings)

    return findings


def _iter_workflow_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*") if p.suffix in WORKFLOW_SUFFIXES and p.is_file())


def validate_directory(root: Path) -> list[Finding]:
    """Validate every workflow file, including failures inherited by callers."""

    directory = root / WORKFLOW_DIRECTORY
    if not directory.is_dir():
        return []

    findings: list[Finding] = []
    per_file: dict[str, list[Finding]] = {}
    parsed: dict[str, Any] = {}

    for file in _iter_workflow_files(directory):
        relative = f"{WORKFLOW_DIRECTORY}/{file.name}"
        text = file.read_text(encoding="utf-8", errors="replace")
        result = validate_text(text, relative)
        per_file[relative] = result
        findings.extend(result)
        try:
            parsed[relative] = yaml.compose(text)
        except yaml.YAMLError:
            parsed[relative] = None

    broken = {name for name, result in per_file.items() if result}
    for relative, node in parsed.items():
        if node is None or relative in broken:
            continue
        for called in sorted(local_called_workflows(node)):
            if called in broken:
                findings.append(
                    Finding(
                        relative,
                        1,
                        "AWV005",
                        (
                            f"calls {called}, which GitHub rejects, so this "
                            f"workflow is invalid too until that file is fixed"
                        ),
                    )
                )

    return sorted(findings, key=lambda f: (f.path, f.line, f.code))
