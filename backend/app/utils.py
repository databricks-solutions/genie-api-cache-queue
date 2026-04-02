import random


def exponential_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff with proportional jitter, hard-capped at *cap*."""
    raw = base * (2 ** attempt)
    jittered = raw + random.uniform(0, raw * 0.5)
    return min(jittered, cap)
