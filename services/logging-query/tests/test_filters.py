from app.filters import build_log_query


def test_query_is_tenant_scoped_and_parameterized():
    sql, values = build_log_query("tenant-a", level="ERROR", search="boom", limit=25)
    assert "tenant_id = $1" in sql
    assert "level = $2" in sql
    assert "message ILIKE $3" in sql
    assert values == ["tenant-a", "ERROR", "%boom%", 25]
    assert "boom" not in sql
