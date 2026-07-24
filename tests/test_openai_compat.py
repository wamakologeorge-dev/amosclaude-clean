from amoscloud_ai.api.routes.openai_compat import _generate_reply
from amoscloud_ai.main import create_app
from amoscloud_ai.route_discovery import route_paths


def test_openai_compatible_routes_are_registered():
    paths = route_paths(create_app().routes)
    assert "/v1/models" in paths
    assert "/v1/chat/completions" in paths


def test_named_gpt_model_uses_server_openai_client(monkeypatch):
    calls = {}

    class Response:
        output_text = "gateway reply"

    class Responses:
        def create(self, **kwargs):
            calls.update(kwargs)
            return Response()

    class Client:
        responses = Responses()

    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    monkeypatch.setattr("openai.OpenAI", lambda api_key: Client())

    reply = _generate_reply("gpt-4.1-mini", [{"role": "user", "content": "hello"}])

    assert reply == "gateway reply"
    assert calls["model"] == "gpt-4.1-mini"
    assert calls["store"] is False
