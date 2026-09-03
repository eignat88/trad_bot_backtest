from datetime import datetime, timedelta, timezone

import pytest

from app.data.historical_provider import Candle
from app.edge_research.dataset import build_edge_rows
from app.edge_research.discovery import temporal_holdout
from app.edge_research.outcomes import evaluate_signal_path


def _candle(minute: int, high: float, low: float, close: float) -> Candle:
    return Candle(minute * 60_000, close, high, low, close, 1.0)


def test_snapshot_rejects_future_source_timestamp():
    signal_time = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    setup = {"setup_id": "x", "scanner_name": "TEST", "symbol": "BTCUSDT", "direction": "LONG",
             "signal_time": signal_time, "source_max_time": signal_time + timedelta(seconds=1)}
    with pytest.raises(ValueError, match="source_max_time"):
        build_edge_rows([setup], {}, feature_set_version="test")


def test_future_candle_mutation_cannot_change_fixed_horizon_outcome():
    baseline = [_candle(1, 101, 99, 101), _candle(5, 102, 100, 102), _candle(6, 999999, 1, 999999)]
    mutated = baseline[:-1] + [_candle(6, 1, 0.1, 0.1)]
    left = evaluate_signal_path(baseline, signal_time_ms=0, signal_close=100, direction="LONG", risk_distance=2, stop_price=98, horizons_minutes=(5,))
    right = evaluate_signal_path(mutated, signal_time_ms=0, signal_close=100, direction="LONG", risk_distance=2, stop_price=98, horizons_minutes=(5,))
    assert left == right
    assert left.return_5m == 1.0


def test_long_and_short_mfe_mae_are_mirrored_and_signed():
    long = evaluate_signal_path([_candle(15, 115, 95, 110)], signal_time_ms=0, signal_close=100,
                                direction="LONG", risk_distance=10, stop_price=90, horizons_minutes=(15,))
    short = evaluate_signal_path([_candle(15, 105, 85, 90)], signal_time_ms=0, signal_close=100,
                                 direction="SHORT", risk_distance=10, stop_price=110, horizons_minutes=(15,))
    assert (long.mfe_15m_r, long.mae_15m_r) == (1.5, -0.5)
    assert (short.mfe_15m_r, short.mae_15m_r) == (1.5, -0.5)


def test_chronological_split_has_no_time_or_setup_overlap():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"setup_id": str(i), "signal_time": start + timedelta(minutes=i)} for i in range(10)]
    discovery, validation = temporal_holdout(list(reversed(rows)), holdout_fraction=.3)
    assert max(row["signal_time"] for row in discovery) < min(row["signal_time"] for row in validation)
    assert {row["setup_id"] for row in discovery}.isdisjoint({row["setup_id"] for row in validation})
