from pathlib import Path

from scripts.amosclaud_autofix import extract_candidate_paths, run_repair


def test_extract_candidate_paths_uses_only_existing_repository_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "worker.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")

    paths = extract_candidate_paths(
        "FAILED src/worker.py:12 and ../../outside.py:1 and missing.py:8",
        tmp_path,
    )

    assert paths == ["src/worker.py"]


def test_extract_candidate_paths_maps_absolute_github_runner_path(tmp_path: Path) -> None:
    source = tmp_path / "src" / "worker.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    runner_path = f"/home/runner/work/{tmp_path.name}/{tmp_path.name}/src/worker.py:12"

    assert extract_candidate_paths(runner_path, tmp_path) == ["src/worker.py"]


def test_run_repair_fixes_only_file_named_by_failed_log(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    unrelated = tmp_path / "unrelated.py"
    target.write_text("answer = 42   ", encoding="utf-8")
    unrelated.write_text("untouched = True   ", encoding="utf-8")

    report = run_repair(tmp_path, "app.py:1: trailing whitespace")

    assert report["status"] == "repaired"
    assert report["changed_files"] == ["app.py"]
    assert target.read_text(encoding="utf-8") == "answer = 42\n"
    assert unrelated.read_text(encoding="utf-8") == "untouched = True   "


def test_run_repair_does_not_guess_when_logs_name_no_file(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("answer = 42   ", encoding="utf-8")

    report = run_repair(tmp_path, "The workflow failed without a file annotation")

    assert report["status"] == "no-candidates"
    assert report["changed_files"] == []
    assert target.read_text(encoding="utf-8") == "answer = 42   "
