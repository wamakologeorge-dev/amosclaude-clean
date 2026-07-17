#!/usr/bin/env python3
"""Build and verify Amosclaud Agent SDK wheel/source artifacts.

No installer or network download is executed. The wheel bundles only code
owned by this repository, including the ``amosclaud-agent`` command.
"""
from __future__ import annotations
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
VERSION_FILE = ROOT / "amosclaud_agent_sdk" / "version.py"

def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)

def replace_version(text: str, version: str, python_file: bool = False) -> str:
    pattern = r'(__version__\s*=\s*)"[^"]+"' if python_file else r'(^version\s*=\s*)"[^"]+"'
    updated, count = re.subn(pattern, rf'\g<1>"{version}"', text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError("Could not locate package version")
    return updated

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="temporary SDK version for this build")
    parser.add_argument("--skip-sdist", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)
    if args.version and not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?", args.version):
        parser.error("--version must be a semantic version")
    if args.clean:
        for path in (ROOT / "build", ROOT / "dist"):
            if path.exists():
                shutil.rmtree(path)
    originals = {path: path.read_text(encoding="utf-8") for path in (PYPROJECT, VERSION_FILE)}
    try:
        if args.version:
            PYPROJECT.write_text(replace_version(originals[PYPROJECT], args.version), encoding="utf-8")
            VERSION_FILE.write_text(replace_version(originals[VERSION_FILE], args.version, True), encoding="utf-8")
        command = [sys.executable, "-m", "build", "--wheel"]
        if not args.skip_sdist:
            command.append("--sdist")
        command.extend(["--outdir", "dist"])
        run(*command)
        artifacts = sorted(str(path) for path in (ROOT / "dist").glob("*"))
        if not artifacts:
            raise RuntimeError("Build produced no artifacts")
        run(sys.executable, "-m", "twine", "check", *artifacts)
    finally:
        for path, content in originals.items():
            path.write_text(content, encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
