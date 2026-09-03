from datetime import datetime, timedelta, timezone

from app.data.historical_provider import Candle
from app.edge_research.dataset import build_edge_rows
from app.edge_research.discovery import discover_univariate_edges, temporal_holdout
from app.edge_research.outcomes import evaluate_signal_path


def candle(index: int, high: float, low: float, close: float) -> Candle:
    return Candle(index * 60_000, close, high, low, close, 1.0)


def test_signal_path_is_independent_of_entry_and_stop_wins_same_bar():
    outcome = evaluate_signal_path(
        [candle(1, 102, 98, 101), candle(2, 103, 100, 102)],
        signal_time_ms=0, signal_close=100, direction="LONG", risk_distance=2, stop_price=98,
    )
    assert outcome.return_5m is None  # no full 5m horizon yet
    assert outcome.mfe_15m_r is None
    assert outcome.hit_10r is True
    assert outcome.hit_stop_before_1r is True
    assert outcome.time_to_stop_min == 1


def test_dataset_flattens_versioned_point_in_time_features():
    at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = build_edge_rows([{
        "setup_id": "s-1", "scanner_name": "BREAKOUT_RETEST", "scanner_version": "v1",
        "symbol": "BTCUSDT", "direction": "LONG", "signal_time": at,
        "features": {"rsi": 55, "enriched": {"volume_zscore": 1.5}},
        "market_context": {"btc_return_4h": 0.02},
    }], {"s-1": {"result_r": 1.0}}, feature_set_version="2026.09.01")
    record = rows[0].as_dict()
    assert record["enriched_volume_zscore"] == 1.5
    assert record["market_btc_return_4h"] == 0.02
    assert record["feature_set_version"] == "2026.09.01"


def test_discovery_uses_fixed_temporal_validation_range():
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(40):
        rows.append({"setup_id": str(index), "signal_time": start + timedelta(days=index), "rsi": 10 if index % 2 else 90,
                     "result_r": 1.0 if index % 2 else -1.0})
    discovery, validation = temporal_holdout(rows, holdout_fraction=.25)
    edges = discover_univariate_edges(discovery, feature_names=["rsi"], bins=2, min_samples=10,
                                      bootstrap_samples=50, validation_rows=validation)
    positive = next(edge for edge in edges if edge.lower == 10)
    assert positive.samples == 15
    assert positive.validation_samples == 5
    assert positive.validation_avg_r == 1.0
    assert positive.bootstrap_probability_positive == 1.0
