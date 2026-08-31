from app.analytics.metrics import calculate_metrics
from app.backtest.outcome import SignalOutcome

def outcome(r: float) -> SignalOutcome:
    return SignalOutcome("1","BTC","TEST","LONG",True,"TP1" if r > 0 else "SL",r,r,max(-1,r),1,1,1,1,r)

def test_metrics_are_r_based_and_track_drawdown():
    metrics = calculate_metrics([outcome(2), outcome(-1), outcome(1)])
    assert metrics.trades == 3
    assert metrics.total_r == 2
    assert metrics.max_drawdown_r == 1
    assert metrics.profit_factor == 3
