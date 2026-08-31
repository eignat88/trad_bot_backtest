"""Deterministic OHLCV resampling from the canonical 1m dataset."""
from __future__ import annotations
from .historical_provider import Candle

_TIMEFRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def resample(candles: tuple[Candle, ...] | list[Candle], timeframe: str) -> tuple[Candle, ...]:
    if timeframe not in _TIMEFRAME_MS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    interval = _TIMEFRAME_MS[timeframe]
    buckets: dict[int, list[Candle]] = {}
    for candle in candles:
        buckets.setdefault(candle.timestamp - candle.timestamp % interval, []).append(candle)
    return tuple(Candle(ts, group[0].open, max(c.high for c in group), min(c.low for c in group), group[-1].close, sum(c.volume for c in group)) for ts, group in sorted(buckets.items()))
