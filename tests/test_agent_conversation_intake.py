from amoscloud_ai.api.routes.agent import _project_intake_reply, _select_autonomous_mode


class Request:
    headers = {}
    cookies = {}


def test_website_intake_asks_for_subject(monkeypatch):
    monkeypatch.setattr("amoscloud_ai.api.routes.agent._display_name", lambda request: "George")
    reply = _project_intake_reply(Request(), "I want to learn how to create a website", {})
    assert "What is the website about?" in reply
    assert "George" in reply


def test_website_intake_asks_what_kind_of_business(monkeypatch):
    monkeypatch.setattr("amoscloud_ai.api.routes.agent._display_name", lambda request: "George")
    metadata = {"conversation": [{"role": "user", "content": "I want to create a website"}]}
    reply = _project_intake_reply(Request(), "The website is about business", metadata)
    assert "What kind of business" in reply


def test_complete_website_brief_is_forwarded_to_execution(monkeypatch):
    monkeypatch.setattr("amoscloud_ai.api.routes.agent._display_name", lambda request: "George")
    metadata = {"conversation": [
        {"role": "user", "content": "I want to create a website"},
        {"role": "user", "content": "The website is about business"},
    ]}
    assert _project_intake_reply(Request(), "An investment platform", metadata) is None
    assert _select_autonomous_mode("build", "An investment platform", metadata) == "fix"
