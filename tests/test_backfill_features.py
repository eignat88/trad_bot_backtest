from app.data.historical_provider import Candle
from app.edge_research.features import calculate_features
from scripts.backfill_edge_dataset import slice_at


def _candle(minute, close):
    return Candle(minute * 60_000, close - .5, close + 1, close - 1, close, 100 + minute)


def test_point_in_time_feature_values_ignore_future_candle_mutation():
    candles = [_candle(i, 100 + i) for i in range(250)]
    as_of = 200 * 60_000
    before = calculate_features(slice_at(candles, as_of), direction="LONG", scanner_score=1, entry=200, stop=190, target=220)
    candles[-1] = _candle(249, 999999)
    after = calculate_features(slice_at(candles, as_of), direction="LONG", scanner_score=1, entry=200, stop=190, target=220)
    assert before == after


def test_feature_calculation_populates_core_fields():
    features = calculate_features([_candle(i, 100 + i * .1) for i in range(250)], direction="LONG", scanner_score=2, entry=124, stop=122, target=128)
    assert features["rsi_14"] is not None
    assert features["ema20_distance_pct"] is not None
    assert features["atr_pct"] is not None
    assert features["volume_ratio_20"] is not None
    assert features["rr_planned"] == 2
