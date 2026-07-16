from amoscloud_ai.main import create_app
from amoscloud_ai.server.cb.Amosclaud import SERVER_ID, SUPPORTED_ACTIONS, _capabilities


def test_server_cb_capabilities_are_bounded():
    capabilities = _capabilities()
    assert capabilities["server_id"] == SERVER_ID
    assert capabilities["arbitrary_code_execution"] is False
    assert capabilities["secret_values_exposed"] is False
    assert set(capabilities["actions"]) == set(SUPPORTED_ACTIONS)


def test_server_cb_routes_are_registered():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/v1/server/cb/amosclaud" in paths
    assert "/api/v1/server/cb/amosclaud/capabilities" in paths
    assert "/api/v1/server/cb/amosclaud/command" in paths
