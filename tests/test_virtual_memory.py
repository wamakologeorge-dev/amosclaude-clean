import pytest

from amoscloud_ai.virtual_memory import GIB, recommended_swap_bytes


@pytest.mark.parametrize(
    ("ram_gib", "swap_gib"),
    [(2, 4), (4, 8), (8, 8), (16, 16), (32, 8), (128, 8)],
)
def test_recommended_swap_is_bounded_and_server_oriented(ram_gib, swap_gib):
    assert recommended_swap_bytes(ram_gib * GIB) == swap_gib * GIB


def test_recommendation_rejects_invalid_memory():
    with pytest.raises(ValueError):
        recommended_swap_bytes(0)
