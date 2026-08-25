"""Deterministic statistics for SLO qualification (stdlib-only).

Registered methods (slo-contract.json -> confidence_intervals):
- latencies: seeded nonparametric percentile bootstrap, B=2000, level 0.95
- proportions: Wilson score interval, level 0.95

Percentiles use the nearest-rank method (same convention as the S1-002
benchmark) so numbers stay comparable across tickets.
"""
from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass


def percentile_nearest_rank(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _seed_from(*parts: object) -> int:
    digest = hashlib.sha256(
        "|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def bootstrap_ci(
    values: list[float],
    *,
    quantile: float,
    b: int = 2000,
    level: float = 0.95,
    seed_parts: tuple = (),
) -> tuple[float, float]:
    """Percentile bootstrap CI for a nearest-rank quantile (or mean)."""
    if not values:
        return (0.0, 0.0)
    import random

    rng = random.Random(_seed_from(len(values), quantile, *seed_parts))
    n = len(values)
    stats: list[float] = []
    for _ in range(b):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        stats.append(percentile_nearest_rank(sample, quantile))
    stats.sort()
    lo_index = max(0, math.ceil((1 - level) / 2 * b) - 1)
    hi_index = min(b - 1, math.ceil((1 + level) / 2 * b) - 1)
    return (stats[lo_index], stats[hi_index])


def wilson_interval(successes: int, total: int, *, level: float = 0.95) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    z = statistics.NormalDist().inv_cdf(1 - (1 - level) / 2)
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class MetricRecord:
    """Registered-shape record for one measured SLI distribution."""

    name: str
    unit: str
    values: list[float]
    seed_parts: tuple = ()
    kind: str = "latency"  # latency | proportion | value

    def to_dict(self, *, include_raw: bool = True) -> dict:
        values = [float(v) for v in self.values]
        record: dict = {
            "name": self.name,
            "unit": self.unit,
            "kind": self.kind,
            "count": len(values),
            "min": round(min(values), 6) if values else None,
            "median": round(statistics.median(values), 6) if values else None,
            "mean": round(statistics.fmean(values), 6) if values else None,
            "p50": round(percentile_nearest_rank(values, 0.50), 6) if values else None,
            "p95": round(percentile_nearest_rank(values, 0.95), 6) if values else None,
            "p99": round(percentile_nearest_rank(values, 0.99), 6) if values else None,
            "max": round(max(values), 6) if values else None,
        }
        if not values:
            record.update({
                "ci95_low": None, "ci95_high": None,
                "ci_method": "none (empty sample)",
            })
        elif self.kind == "proportion":
            # values encode success fractions per observation batch? No:
            # proportions arrive as (successes,total) pairs via proportion_record.
            raise ValueError("use proportion_record() for kind='proportion'")
        else:
            lo, hi = bootstrap_ci(
                values, quantile=0.95,
                seed_parts=(self.name, *self.seed_parts))
            record["ci95_low"] = round(lo, 6)
            record["ci95_high"] = round(hi, 6)
            record["ci_method"] = "bootstrap_percentile_B2000_level0.95"
        if include_raw:
            record["raw"] = values
        return record


def proportion_record(name: str, successes: int, total: int, *, unit: str = "fraction",
                      seed_parts: tuple = ()) -> dict:
    lo, hi = wilson_interval(successes, total)
    p = (successes / total) if total else None
    return {
        "name": name,
        "unit": unit,
        "kind": "proportion",
        "count": total,
        "successes": successes,
        "value": round(p, 9) if p is not None else None,
        "ci95_low": round(lo, 9),
        "ci95_high": round(hi, 9),
        "ci_method": "wilson_score_level0.95",
        "raw": [successes, total],
    }


def sufficient_power(record: dict, minimum_observations: int) -> bool:
    count = record.get("count", 0)
    return isinstance(count, int) and count >= minimum_observations
