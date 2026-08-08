from app.redaction.service import redact


def test_nested_secrets_are_removed():
    value = {"authorization": "Bearer secret-value", "nested": {"api_key": "abc"}}
    assert redact(value) == {
        "authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]"},
    }


def test_tokens_inside_messages_are_removed():
    output = redact({"message": "Authorization Bearer abcdefghijklmnop"})
    assert "abcdefghijklmnop" not in output["message"]
