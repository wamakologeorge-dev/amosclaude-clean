from pathlib import Path


def _web_file(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "web" / name).read_text(encoding="utf-8")


def test_autonomous_calls_real_authenticated_bundles_api():
    script = _web_file("conversational-agent.js")

    assert "fetch('/api/v1/bundles'" in script
    assert "bundle_type" in script
    assert "archive_sha256" in script
    assert "latestBundleResult" in script
    assert "Proceed with the plan" in script


def test_all_real_bundle_types_are_classified():
    script = _web_file("conversational-agent.js")

    for bundle_type in ("source", "runtime", "connector", "deployment", "extension"):
        assert f"['{bundle_type}'" in script


def test_deployment_bundle_requires_real_entrypoint():
    script = _web_file("conversational-agent.js")

    assert "bundleDraft.bundle_type !== 'deployment' || bundleDraft.entrypoint" in script
    assert "What exact entrypoint" in script


def test_real_result_card_shows_manifest_and_integrity_evidence():
    script = _web_file("autonomous-result-cards.js")
    html = _web_file("index.html")

    assert "Verified real bundle record" in script
    assert "Bundle ID" in script
    assert "Archive SHA-256" in script
    assert "Included files" in script
    assert "Download verified .amosbundle" in script
    assert "/static/autonomous-result-cards.js" in html
    assert "/static/autonomous-result-cards.css" in html


def test_no_fake_or_placeholder_bundle_result_data_is_present():
    content = "\n".join(
        _web_file(name).lower()
        for name in ("conversational-agent.js", "autonomous-result-cards.js", "index.html")
    )

    for forbidden in ("sample result", "demo result", "fake result", "placeholder result"):
        assert forbidden not in content
