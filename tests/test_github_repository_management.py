from __future__ import annotations

import base64

import httpx
import pytest
from fastapi import HTTPException
from nacl.public import PrivateKey, SealedBox
from starlette.requests import Request

from amoscloud_ai.api.routes import github_repository_management as management


def _request(intent: bool = True) -> Request:
    headers = []
    if intent:
        headers.append((b"x-amosclaud-intent", b"repository-management"))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def _context(*, scopes: frozenset[str] | None = None) -> management.RepositoryContext:
    return management.RepositoryContext(
        repository_id=12,
        user_id=7,
        full_name="octocat/example",
        token="token",
        scopes=scopes or frozenset({"repo"}),
        metadata={"permissions": {"admin": True}},
    )


def _json_response(status_code: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload or {},
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


def test_actions_secret_encryption_round_trip() -> None:
    private_key = PrivateKey.generate()
    encoded_public_key = base64.b64encode(bytes(private_key.public_key)).decode("ascii")

    encrypted = management._encrypt_actions_secret(encoded_public_key, "very-sensitive")
    decrypted = SealedBox(private_key).decrypt(base64.b64decode(encrypted)).decode("utf-8")

    assert decrypted == "very-sensitive"


def test_actions_names_are_normalized_and_reserved_prefix_is_rejected() -> None:
    assert management._clean_actions_name(" deploy_token ") == "DEPLOY_TOKEN"

    with pytest.raises(HTTPException) as reserved:
        management._clean_actions_name("github_token")
    assert reserved.value.status_code == 422

    with pytest.raises(HTTPException) as invalid:
        management._clean_actions_name("2bad-name")
    assert invalid.value.status_code == 422


def test_webhook_requires_https_and_normalizes_events() -> None:
    assert management._clean_webhook_url(" https://example.com/github ") == (
        "https://example.com/github"
    )
    assert management._clean_webhook_events(["Push", "push", "pull_request"]) == [
        "push",
        "pull_request",
    ]

    with pytest.raises(HTTPException) as insecure:
        management._clean_webhook_url("http://example.com/github")
    assert insecure.value.status_code == 422


def test_mutations_require_explicit_intent_header() -> None:
    management._mutation_guard(_request())

    with pytest.raises(HTTPException) as missing:
        management._mutation_guard(_request(intent=False))
    assert missing.value.status_code == 400


def test_archive_requires_exact_repository_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(management, "_repository_context", lambda *_args, **_kwargs: _context())

    with pytest.raises(HTTPException) as mismatch:
        management.set_repository_archive_state(
            12,
            management.ArchiveRequest(
                archived=True,
                confirm_repository="octocat/wrong",
            ),
            _request(),
            {"id": 7},
        )
    assert mismatch.value.status_code == 422


def test_delete_requires_delete_scope_before_remote_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(management, "_repository_context", lambda *_args, **_kwargs: _context())
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("GitHub must not be called without delete_repo scope")

    monkeypatch.setattr(management, "_request_github", fail_if_called)

    with pytest.raises(HTTPException) as missing_scope:
        management.delete_repository(
            12,
            management.DeleteRepositoryRequest(
                confirm_repository="octocat/example",
                acknowledge_irreversible=True,
            ),
            _request(),
            {"id": 7},
        )

    assert missing_scope.value.status_code == 403
    assert called is False


def test_delete_removes_local_workspace_only_after_github_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(scopes=frozenset({"repo", "delete_repo"}))
    events: list[str] = []
    monkeypatch.setattr(management, "_repository_context", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(
        management,
        "_request_github",
        lambda *_args, **_kwargs: events.append("github") or _json_response(204),
    )
    monkeypatch.setattr(management, "_audit", lambda *_args, **_kwargs: events.append("audit"))
    monkeypatch.setattr(
        management,
        "_remove_local_repository",
        lambda *_args, **_kwargs: events.append("local"),
    )

    response = management.delete_repository(
        12,
        management.DeleteRepositoryRequest(
            confirm_repository="octocat/example",
            acknowledge_irreversible=True,
        ),
        _request(),
        {"id": 7},
    )

    assert response.status_code == 204
    assert events == ["github", "audit", "local"]


def test_secret_response_never_returns_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = PrivateKey.generate()
    context = _context()
    calls = 0

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _json_response(
                200,
                {
                    "key_id": "key-1",
                    "key": base64.b64encode(bytes(private_key.public_key)).decode("ascii"),
                },
            )
        body = _kwargs["json_body"]
        decrypted = SealedBox(private_key).decrypt(base64.b64decode(str(body["encrypted_value"])))
        assert decrypted == b"secret-value"
        return _json_response(201)

    monkeypatch.setattr(management, "_repository_context", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(management, "_request_github", fake_request)
    monkeypatch.setattr(management, "_audit", lambda *_args, **_kwargs: None)

    payload = management.put_repository_secret(
        12,
        "deploy_token",
        management.SecretValueRequest(value="secret-value"),
        _request(),
        {"id": 7},
    )

    assert payload == {
        "repository_id": 12,
        "name": "DEPLOY_TOKEN",
        "created": True,
        "value_returned": False,
    }
    assert "secret-value" not in str(payload)
