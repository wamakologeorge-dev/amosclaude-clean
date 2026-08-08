from app.fingerprint import fingerprint


def test_changing_ids_do_not_split_same_incident():
    base = {"tenant_id": "t", "service": "api", "level": "ERROR"}
    first = fingerprint({**base, "message": "request 123 failed"})
    second = fingerprint({**base, "message": "request 456 failed"})
    assert first == second
