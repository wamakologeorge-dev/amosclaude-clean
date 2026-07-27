from amoscloud_ai.live_repair_probe import add_numbers


def test_add_numbers_returns_arithmetic_sum() -> None:
    assert add_numbers(3, 4) == 7
    assert add_numbers(-2, 5) == 3
