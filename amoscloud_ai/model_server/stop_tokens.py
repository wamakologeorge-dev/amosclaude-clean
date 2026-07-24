"""Stop-token and stop-sequence evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StopEvaluator:
    eos_token_ids: set[int] = field(default_factory=set)
    stop_sequences: tuple[str, ...] = ()

    def should_stop(
        self,
        token_id: int,
        decoded_text: str,
    ) -> tuple[bool, str | None]:
        if token_id in self.eos_token_ids:
            return True, "eos_token"
        for sequence in self.stop_sequences:
            if sequence and decoded_text.endswith(sequence):
                return True, f"stop_sequence:{sequence}"
        return False, None

    def trim(self, text: str) -> str:
        earliest: int | None = None
        for sequence in self.stop_sequences:
            index = text.find(sequence)
            if index >= 0 and (earliest is None or index < earliest):
                earliest = index
        if earliest is None:
            return text
        return text[:earliest]
