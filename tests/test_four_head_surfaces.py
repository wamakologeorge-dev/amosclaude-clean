from pathlib import Path


HEAD_FILES = (
    Path("index.html"),
    Path("web/index.html"),
    Path("public/index.html"),
    Path("src/amoscloud_ai/templates/index.html"),
)


def test_all_four_heads_use_one_autonomous_identity() -> None:
    for path in HEAD_FILES:
        content = path.read_text(encoding="utf-8")
        assert 'data-amosclaud-head="true"' in content, path
        assert "Amosclaud Autonomous" in content, path
        assert "Repository" in content, path
        assert "Results" in content, path
        assert "one identity" in content.lower(), path


def test_all_four_heads_expose_job_proof_contract() -> None:
    required_meanings = ("instructions", "permission", "evidence", "final")
    for path in HEAD_FILES:
        content = path.read_text(encoding="utf-8").lower()
        for meaning in required_meanings:
            assert meaning in content, f"{path} is missing {meaning}"


def test_legacy_public_head_no_longer_presents_cmood_agents() -> None:
    content = Path("public/index.html").read_text(encoding="utf-8").lower()
    assert "cmood agent" not in content
    assert "mood agent" not in content
