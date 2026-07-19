from __future__ import annotations

import math


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total
    denominator = 1 + (z * z / total)
    center = (phat + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt((phat * (1 - phat) / total) + (z * z / (4 * total * total)))
        / denominator
    )
    return round(max(0.0, center - margin), 3), round(min(1.0, center + margin), 3)


def brier_score_binary(probability: float, target: float) -> float:
    return round((probability - target) ** 2, 3)
