import random


def exponential_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff with proportional jitter."""
    delay = min(base * (2 ** attempt), cap)
    return delay + random.uniform(0, delay * 0.5)
