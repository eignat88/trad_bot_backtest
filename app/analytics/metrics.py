"""R-multiple based performance metrics for signal backtests."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from math import sqrt
from statistics import mean, pstdev
from typing import Iterable
from app.backtest.outcome import SignalOutcome

@dataclass(frozen=True)
class PerformanceMetrics:
    signals: int; trades: int; wins: int; losses: int; win_rate: float; total_r: float; avg_r: float
    expectancy: float; profit_factor: float; max_drawdown_r: float; sharpe: float; sortino: float
    avg_mfe_r: float; avg_mae_r: float; fee_impact_r: float
    def to_dict(self) -> dict: return asdict(self)


def calculate_metrics(outcomes: Iterable[SignalOutcome]) -> PerformanceMetrics:
    values = list(outcomes); entered = [o for o in values if o.entry_touched]
    r = [o.fee_slippage_adjusted_result_r for o in entered]
    wins = [x for x in r if x > 0]; losses = [x for x in r if x < 0]
    equity = peak = 0.0; max_dd = 0.0
    for value in r:
        equity += value; peak = max(peak, equity); max_dd = max(max_dd, peak-equity)
    avg = mean(r) if r else 0.0
    deviation = pstdev(r) if len(r) > 1 else 0.0
    downside = pstdev([min(0.0, x) for x in r]) if len(r) > 1 else 0.0
    gross_loss = abs(sum(losses))
    return PerformanceMetrics(len(values), len(entered), len(wins), len(losses), round(len(wins)/len(entered), 6) if entered else 0.0, round(sum(r), 6), round(avg, 6), round(avg, 6), round(sum(wins)/gross_loss, 6) if gross_loss else float("inf") if wins else 0.0, round(max_dd, 6), round(avg/deviation*sqrt(len(r)), 6) if deviation else 0.0, round(avg/downside*sqrt(len(r)), 6) if downside else 0.0, round(mean([o.mfe_r for o in entered]), 6) if entered else 0.0, round(mean([o.mae_r for o in entered]), 6) if entered else 0.0, round(sum(o.result_r-o.fee_slippage_adjusted_result_r for o in entered), 6))


def composite_objective(metrics: PerformanceMetrics, *, minimum_trades: int = 100) -> float:
    """Reward expectancy/quality, penalize drawdown and insufficient sample size."""
    if metrics.trades < minimum_trades: return float("-inf")
    pf = min(metrics.profit_factor, 5.0)
    return round(metrics.expectancy + 0.15 * pf + 0.05 * metrics.sharpe - 0.10 * metrics.max_drawdown_r, 6)
