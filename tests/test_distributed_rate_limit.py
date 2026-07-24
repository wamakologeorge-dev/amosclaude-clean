from unittest.mock import Mock

from amoscloud_ai.security import SecurityMiddleware


def test_redis_rate_limit_is_shared(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid/0")
    monkeypatch.setenv("AUTH_RATE_MAX_ATTEMPTS", "2")
    middleware = SecurityMiddleware(Mock())
    store = {}
    fake = Mock()
    fake.incr.side_effect = lambda key: store.setdefault(key, 0) + 1

    def increment(key):
        store[key] = store.get(key, 0) + 1
        return store[key]

    fake.incr.side_effect = increment
    middleware.redis = fake
    request = Mock()
    request.method = "POST"
    request.url.path = "/api/v1/auth/login"
    request.client.host = "127.0.0.1"
    request.headers = {}
    assert middleware._rate_limited(request) is False
    assert middleware._rate_limited(request) is False
    assert middleware._rate_limited(request) is True
