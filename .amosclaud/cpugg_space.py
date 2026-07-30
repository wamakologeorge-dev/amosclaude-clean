"""Electron-shell utilities for neutral atoms."""

from __future__ import annotations

SUBSHELL_FILL_ORDER: tuple[tuple[int, int], ...] = (
    (1, 2),
    (2, 2),
    (2, 6),
    (3, 2),
    (3, 6),
    (4, 2),
    (3, 10),
    (4, 6),
    (5, 2),
    (4, 10),
    (5, 6),
    (6, 2),
    (4, 14),
    (5, 10),
    (6, 6),
    (7, 2),
    (5, 14),
    (6, 10),
    (7, 6),
)


def get_electron_shells(atomic_number: int) -> list[int]:
    """Return electron counts grouped by principal shell for a neutral atom.

    Electrons are populated in subshell energy order and then aggregated by
    principal shell. The supported range covers the known elements, 1-118.
    """
    if isinstance(atomic_number, bool) or not isinstance(atomic_number, int):
        raise TypeError("atomic_number must be an integer")
    if not 1 <= atomic_number <= 118:
        raise ValueError("atomic_number must be between 1 and 118")

    shell_totals = [0] * 7
    remaining_electrons = atomic_number

    for shell_number, capacity in SUBSHELL_FILL_ORDER:
        if remaining_electrons == 0:
            break
        electrons_in_subshell = min(remaining_electrons, capacity)
        shell_totals[shell_number - 1] += electrons_in_subshell
        remaining_electrons -= electrons_in_subshell

    while shell_totals[-1] == 0:
        shell_totals.pop()

    return shell_totals


if __name__ == "__main__":
    print(f"Carbon electron configuration by shell: {get_electron_shells(6)}")
