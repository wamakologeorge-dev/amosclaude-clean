from fastapi import Request

from amoscloud_ai.security import (
    OWNER_CALLBACK_PATHS,
    REPOSITORY_CALLBACK_PATH,
    _route_repository_oauth_callback,
)


def _request(path: str, state: str, cookie_state: str | None) -> Request:
    headers = []
    if cookie_state is not None:
        headers.append(
            (b"cookie", f"amos_github_oauth_state={cookie_state}".encode())
        )
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": f"code=test-code&state={state}".encode(),
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("www.amosclaud.com", 443),
            "root_path": "",
        }
    )


def test_repository_flow_is_routed_from_the_shared_owner_callback() -> None:
    request = _request(
        "/api/v1/auth/github/admin-callback",
        "repository-state",
        "repository-state",
    )

    _route_repository_oauth_callback(request)

    assert request.scope["path"] == REPOSITORY_CALLBACK_PATH
    assert request.scope["raw_path"] == REPOSITORY_CALLBACK_PATH.encode()


def test_owner_flow_stays_on_the_owner_callback() -> None:
    owner_path = next(iter(OWNER_CALLBACK_PATHS))
    request = _request(owner_path, "owner-state", "stale-repository-state")

    _route_repository_oauth_callback(request)

    assert request.scope["path"] == owner_path


def test_callback_without_repository_cookie_is_not_rerouted() -> None:
    owner_path = "/api/v1/auth/github/admin-callback"
    request = _request(owner_path, "owner-state", None)

    _route_repository_oauth_callback(request)

    assert request.scope["path"] == owner_path
