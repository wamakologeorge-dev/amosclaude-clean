from cmood.agent import main, process_latest_changes


def test_cmood_one_shot_agent_observes_repository(tmp_path):
    (tmp_path / "source.py").write_text("print('ready')", encoding="utf-8")
    result = process_latest_changes("owner/repo", "abc123", tmp_path)
    assert result["status"] == "completed"
    assert result["files_observed"] == 1


def test_cmood_cli_entrypoint(capsys):
    assert (
        main(["--task", "process_latest_changes", "--repo", "owner/repo", "--ref", "abc123"]) == 0
    )
    assert '"status": "completed"' in capsys.readouterr().out
