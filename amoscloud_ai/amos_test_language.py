"""Amosclaud Focused Server Tests language and runner.

The .amos syntax is intentionally small and human-readable:

    AMOSCLAUD SERVER-TESTS 1
    FOCUS health
    CALL GET /health
    EXPECT STATUS 200
    EXPECT JSON status = "ok"
    END

It runs directly against the FastAPI ASGI application and does not depend on
pytest for production health verification.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class Expectation:
    kind: str
    key: str | None = None
    value: Any = None


@dataclass
class FocusCase:
    name: str
    method: str = "GET"
    path: str = "/"
    expectations: list[Expectation] = field(default_factory=list)


@dataclass
class FocusResult:
    name: str
    passed: bool
    evidence: list[str]


class AmosTestSyntaxError(ValueError):
    pass


def _value(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def parse_amos_tests(source: str) -> list[FocusCase]:
    lines = [(number, raw.strip()) for number, raw in enumerate(source.splitlines(), 1)]
    lines = [(number, line) for number, line in lines if line and not line.startswith("#")]
    if not lines or lines[0][1] != "AMOSCLAUD SERVER-TESTS 1":
        raise AmosTestSyntaxError("First line must be: AMOSCLAUD SERVER-TESTS 1")

    cases: list[FocusCase] = []
    current: FocusCase | None = None
    for number, line in lines[1:]:
        parts = shlex.split(line)
        if not parts:
            continue
        command = parts[0].upper()
        if command == "FOCUS":
            if current is not None:
                raise AmosTestSyntaxError(f"line {number}: previous FOCUS requires END")
            if len(parts) < 2:
                raise AmosTestSyntaxError(f"line {number}: FOCUS requires a name")
            current = FocusCase(" ".join(parts[1:]))
        elif command == "CALL":
            if current is None or len(parts) != 3:
                raise AmosTestSyntaxError(f"line {number}: CALL requires METHOD and PATH inside FOCUS")
            current.method, current.path = parts[1].upper(), parts[2]
        elif command == "EXPECT":
            if current is None or len(parts) < 3:
                raise AmosTestSyntaxError(f"line {number}: malformed EXPECT")
            kind = parts[1].upper()
            if kind == "STATUS" and len(parts) == 3:
                current.expectations.append(Expectation("status", value=int(parts[2])))
            elif kind == "TEXT" and len(parts) >= 4 and parts[2].upper() == "CONTAINS":
                current.expectations.append(Expectation("text_contains", value=" ".join(parts[3:])))
            elif kind == "HEADER" and len(parts) >= 5 and parts[3] == "=":
                current.expectations.append(Expectation("header", key=parts[2].lower(), value=" ".join(parts[4:])))
            elif kind == "JSON" and len(parts) >= 5 and parts[3] == "=":
                current.expectations.append(Expectation("json", key=parts[2], value=_value(" ".join(parts[4:]))))
            else:
                raise AmosTestSyntaxError(f"line {number}: unsupported EXPECT form")
        elif command == "END":
            if current is None:
                raise AmosTestSyntaxError(f"line {number}: END without FOCUS")
            if not current.expectations:
                raise AmosTestSyntaxError(f"line {number}: FOCUS has no expectations")
            cases.append(current)
            current = None
        else:
            raise AmosTestSyntaxError(f"line {number}: unknown command {command}")
    if current is not None:
        raise AmosTestSyntaxError("Last FOCUS requires END")
    return cases


def _json_path(data: Any, path: str) -> Any:
    value = data
    for segment in path.split("."):
        if isinstance(value, dict) and segment in value:
            value = value[segment]
        else:
            raise KeyError(path)
    return value


async def run_cases(cases: list[FocusCase]) -> list[FocusResult]:
    from amoscloud_ai.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    results: list[FocusResult] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://amosclaud.test") as client:
        for case in cases:
            response = await client.request(case.method, case.path, follow_redirects=False)
            evidence = [f"CALL {case.method} {case.path} -> {response.status_code}"]
            passed = True
            for expectation in case.expectations:
                try:
                    if expectation.kind == "status":
                        actual = response.status_code
                    elif expectation.kind == "text_contains":
                        actual = expectation.value in response.text
                        expectation = Expectation(expectation.kind, value=True)
                    elif expectation.kind == "header":
                        actual = response.headers.get(expectation.key or "")
                    elif expectation.kind == "json":
                        actual = _json_path(response.json(), expectation.key or "")
                    else:
                        raise AssertionError(f"unknown expectation {expectation.kind}")
                    ok = actual == expectation.value
                    evidence.append(f"EXPECT {expectation.kind} {expectation.key or ''}: {actual!r} {'PASS' if ok else 'FAIL'}")
                    passed = passed and ok
                except Exception as exc:
                    passed = False
                    evidence.append(f"EXPECT {expectation.kind} ERROR: {type(exc).__name__}: {exc}")
            results.append(FocusResult(case.name, passed, evidence))
    return results


def run_file(path: Path) -> list[FocusResult]:
    cases = parse_amos_tests(path.read_text(encoding="utf-8"))
    return asyncio.run(run_cases(cases))


def main() -> int:
    parser = argparse.ArgumentParser(prog="amos-server-tests")
    parser.add_argument("file", nargs="?", default="tests/server.focus.amos")
    args = parser.parse_args()
    try:
        results = run_file(Path(args.file))
    except Exception as exc:
        print(f"AMOS SERVER-TESTS SYNTAX FAILED: {type(exc).__name__}: {exc}")
        return 2
    passed = sum(result.passed for result in results)
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'} FOCUS {result.name}")
        for item in result.evidence:
            print(f"  {item}")
    print(f"AMOS SERVER-TESTS: {passed}/{len(results)} focused checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
