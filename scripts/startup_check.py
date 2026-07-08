#!/usr/bin/env python3
"""Minimal startup verification for Amoscloud AI service."""

import importlib
import sys


def check_import(module_path: str) -> bool:
    try:
        importlib.import_module(module_path)
        print(f"✅ Import OK: {module_path}")
        return True
    except Exception as exc:
        print(f"❌ Import failed: {module_path} -> {exc}")
        return False


def main() -> int:
    ok = True
    ok = check_import("src.amoscloud_ai.main") and ok

    if ok:
        print("✅ Startup precheck passed")
        return 0

    print("❌ Startup precheck failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
