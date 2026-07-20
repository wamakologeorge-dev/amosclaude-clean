from pathlib import Path


def _read(relative: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / relative).read_text(encoding="utf-8")


def test_shared_app_script_treats_page_specific_elements_as_optional():
    script = _read("web/app.js")

    assert "function bind(id, eventName, handler)" in script
    assert "if (!dot && !label) return;" in script
    assert "if (!tbody) return;" in script
    assert "$('modal-backdrop').addEventListener" not in script
    assert "$('btn-trigger-pipeline').addEventListener" not in script


def test_health_and_agent_requests_update_green_states():
    script = _read("web/app.js")

    assert "status-dot status-ok" in script
    assert "Server alive" in script
    assert "badge badge-success" in script
    assert "credentials: 'same-origin'" in script
    assert "cache: 'no-store'" in script


def test_cloud_agent_send_button_is_not_bound_twice():
    script = _read("web/app.js")

    assert "document.body.dataset.legacyAgentRunner === 'true'" in script
    assert "The cloud-agent page owns its Send button through conversational-agent.js." in script
