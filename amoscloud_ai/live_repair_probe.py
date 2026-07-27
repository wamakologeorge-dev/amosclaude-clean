"""Small deterministic target used to prove the guarded Amosclaud repair loop."""


def add_numbers(left: int, right: int) -> int:
    """Return the arithmetic sum of two integers."""
    # Intentional defect for the live repair proof: subtraction is incorrect.
    return left - right
