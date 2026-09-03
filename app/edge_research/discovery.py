"""Leakage-aware, explainable conditional-expectancy discovery utilities."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from random import Random
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class CandidateEdge:
    feature: str
    lower: float
    upper: float
    samples: int
    win_rate: float
    avg_r: float
    median_r: float
    profit_factor: float | None
    bootstrap_probability_positive: float
    validation_avg_r: float | None = None
    validation_samples: int = 0


def temporal_holdout(rows: Sequence[Mapping[str, Any]], *, holdout_fraction: float = .25) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Chronologically split rows; never select a condition using holdout data."""
    if not 0 < holdout_fraction < 1:
        raise ValueError("holdout_fraction must be between zero and one")
    if len(rows) < 2:
        raise ValueError("at least two rows are required for a holdout")
    if any("setup_id" not in row for row in rows):
        raise ValueError("rows require setup_id for split-overlap validation")
    setup_ids = [str(row["setup_id"]) for row in rows]
    if len(set(setup_ids)) != len(setup_ids):
        raise ValueError("duplicate setup_id violates the one-row-per-setup dataset grain")
    ordered = sorted(rows, key=lambda row: _time(row))
    pivot = max(1, int(len(ordered) * (1 - holdout_fraction)))
    return ordered[:pivot], ordered[pivot:]


def discover_univariate_edges(
    rows: Sequence[Mapping[str, Any]], *, feature_names: Iterable[str], outcome: str = "result_r",
    bins: int = 5, min_samples: int = 30, bootstrap_samples: int = 500, seed: int = 7,
    validation_rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[CandidateEdge, ...]:
    """Find stable quantile regions on discovery data and score a fixed validation set.

    It deliberately returns *all* qualifying buckets rather than declaring a proven
    edge: callers must use a final untouched OOS period / walk-forward test.
    """
    if bins < 2 or min_samples < 1 or bootstrap_samples < 1:
        raise ValueError("bins >= 2, min_samples >= 1, bootstrap_samples >= 1 required")
    candidates: list[CandidateEdge] = []
    for feature in feature_names:
        sample = [(float(row[feature]), float(row[outcome])) for row in rows if _number(row.get(feature)) and _number(row.get(outcome))]
        if len(sample) < min_samples:
            continue
        values = sorted(item[0] for item in sample)
        edges = _quantile_edges(values, bins)
        for lower, upper, final in edges:
            results = [result for value, result in sample if lower <= value <= upper if final or value < upper]
            if len(results) < min_samples:
                continue
            validation = _results_in_range(validation_rows or (), feature, outcome, lower, upper, final)
            candidates.append(CandidateEdge(
                feature=feature, lower=lower, upper=upper, samples=len(results),
                win_rate=round(sum(value > 0 for value in results) / len(results), 6),
                avg_r=round(sum(results) / len(results), 6), median_r=round(median(results), 6),
                profit_factor=_profit_factor(results),
                bootstrap_probability_positive=round(_bootstrap_positive(results, bootstrap_samples, seed), 6),
                validation_avg_r=round(sum(validation) / len(validation), 6) if validation else None,
                validation_samples=len(validation),
            ))
    return tuple(sorted(candidates, key=lambda edge: (edge.validation_avg_r if edge.validation_avg_r is not None else edge.avg_r, edge.samples), reverse=True))


def _time(row: Mapping[str, Any]) -> datetime:
    value = row.get("signal_time", row.get("detected_at"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("rows require timezone-aware signal_time or detected_at")
    return value


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _quantile_edges(values: list[float], bins: int) -> list[tuple[float, float, bool]]:
    edges: list[float] = []
    for index in range(bins + 1):
        position = index * (len(values) - 1) / bins
        low, high = int(position), min(int(position) + 1, len(values) - 1)
        edges.append(values[low] + (values[high] - values[low]) * (position - low))
    return [(edges[index], edges[index + 1], index == bins - 1) for index in range(bins) if edges[index] < edges[index + 1]]


def _results_in_range(rows: Sequence[Mapping[str, Any]], feature: str, outcome: str, lower: float, upper: float, final: bool) -> list[float]:
    return [float(row[outcome]) for row in rows if _number(row.get(feature)) and _number(row.get(outcome)) and lower <= float(row[feature]) <= upper and (final or float(row[feature]) < upper)]


def _profit_factor(results: list[float]) -> float | None:
    gains = sum(value for value in results if value > 0)
    losses = -sum(value for value in results if value < 0)
    return round(gains / losses, 6) if losses else None


def _bootstrap_positive(results: list[float], draws: int, seed: int) -> float:
    rng = Random(seed)
    wins = 0
    for _ in range(draws):
        average = sum(rng.choice(results) for _ in results) / len(results)
        wins += average > 0
    return wins / draws
