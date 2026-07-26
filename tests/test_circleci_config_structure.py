"""Contracts for the repository's authoritative CircleCI verification config."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".circleci" / "config.yml"


def _top_level_key_count(source: str, key: str) -> int:
    return sum(1 for line in source.splitlines() if line == f"{key}:")


def test_circleci_config_has_one_authoritative_top_level_section_each() -> None:
    source = CONFIG_PATH.read_text(encoding="utf-8")

    for key in ("executors", "commands", "jobs", "workflows"):
        assert _top_level_key_count(source, key) == 1


def test_circleci_verify_job_uses_declared_python_executor() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["executors"]["python311"]["docker"][0]["image"] == "cimg/python:3.11"
    assert config["executors"]["python311"]["resource_class"] == "medium"
    assert config["jobs"]["verify"]["executor"] == "python311"
    assert config["workflows"]["verify-amosclaud-platform"]["jobs"] == ["verify"]
