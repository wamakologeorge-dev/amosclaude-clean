from app.retry import RetryPolicy


def test_retry_is_bounded():
    policy = RetryPolicy(max_attempts=3, base_delay_seconds=1, maximum_delay_seconds=3)
    assert policy.delay(1) == 1
    assert policy.delay(3) == 3
    assert policy.delay(99) == 3
    assert policy.should_dead_letter(3)
