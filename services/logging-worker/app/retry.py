from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 0.25
    maximum_delay_seconds: float = 30.0

    def delay(self, attempt: int) -> float:
        return min(self.maximum_delay_seconds, self.base_delay_seconds * (2 ** max(0, attempt - 1)))

    def should_dead_letter(self, attempt: int) -> bool:
        return attempt >= self.max_attempts
