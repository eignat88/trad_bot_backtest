from app.analytics.metrics import calculate_metrics, composite_objective, passes_edge_filters
from app.backtest.outcome import SignalOutcome

def outcome(r: float) -> SignalOutcome:
    return SignalOutcome("1","BTC","TEST","LONG",True,"TP1" if r > 0 else "SL",r,r,max(-1,r),1,1,1,1,r)

def test_metrics_are_r_based_and_track_drawdown():
    metrics = calculate_metrics([outcome(2), outcome(-1), outcome(1)])
    assert metrics.trades == 3
    assert metrics.total_r == 2
    assert metrics.max_drawdown_r == 1
    assert metrics.profit_factor == 3


def test_edge_filters_gate_grid_search_candidates():
    good = calculate_metrics([outcome(0.5)] * 101 + [outcome(-1)] * 20)
    too_few = calculate_metrics([outcome(0.5)] * 20)
    negative = calculate_metrics([outcome(0.5)] * 50 + [outcome(-1)] * 60)

    assert passes_edge_filters(good, minimum_trades=100)
    assert composite_objective(good, minimum_trades=100) > float("-inf")
    assert not passes_edge_filters(too_few, minimum_trades=100)
    assert composite_objective(too_few, minimum_trades=100) == float("-inf")
    assert not passes_edge_filters(negative, minimum_trades=100)
