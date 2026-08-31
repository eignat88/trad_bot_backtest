from datetime import datetime, timezone
from uuid import uuid4
from app.backtest.outcome import evaluate_setup_outcome
from app.data.historical_provider import Candle, HistoricalClock, HistoricalDataProvider, InMemoryCandleRepository

class Setup:
    setup_id=uuid4(); symbol="BTCUSDT"; scanner_name="TREND_PULLBACK"; direction="LONG"; signal_candle_open_time=1_000
    entry_zone_low=99.; entry_zone_high=100.; invalidation_price=98.; target_1=102.; target_2=104.

def test_provider_hides_future_candles():
    clock=HistoricalClock(datetime.fromtimestamp(2, timezone.utc))
    provider=HistoricalDataProvider(InMemoryCandleRepository({("BTCUSDT","1m"):(Candle(1_000,1,1,1,1,1), Candle(3_000,2,2,2,2,2))}), clock)
    assert [c.timestamp for c in provider.get_candles("BTCUSDT", "1m")] == [1_000]

def test_stop_wins_when_stop_and_target_touch_same_candle():
    outcome=evaluate_setup_outcome(Setup(), [Candle(2_000, 100, 103, 97, 101, 1)])
    assert outcome.first_event == "SL"
    assert outcome.result_r == -1.0

def test_tp2_result_is_measured_in_r():
    outcome=evaluate_setup_outcome(Setup(), [Candle(2_000,100,105,99,104,1)])
    assert outcome.first_event == "TP2"
    assert outcome.result_r == 2.0
