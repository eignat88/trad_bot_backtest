"""Level-1 scanner → outcome engine, intended for fast parameter research."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Sequence
from app.analytics.metrics import PerformanceMetrics, calculate_metrics
from app.backtest.outcome import SignalOutcome, evaluate_setup_outcome
from app.data.historical_provider import Candle, HistoricalClock, HistoricalDataProvider

@dataclass(frozen=True)
class SignalBacktestResult:
    run_id: str; outcomes: tuple[SignalOutcome, ...]; metrics: PerformanceMetrics

class SignalBacktest:
    def __init__(self, provider: HistoricalDataProvider, scanner: Callable[[str, HistoricalDataProvider], Iterable[object]], *, fee_slippage_r: float = 0.0, max_bars: int = 48) -> None:
        self.provider, self.scanner = provider, scanner
        self.fee_slippage_r, self.max_bars = fee_slippage_r, max_bars

    def run(self, *, run_id: str, symbols: Sequence[str], start: datetime, end: datetime, step: timedelta) -> SignalBacktestResult:
        if start.tzinfo is None or end.tzinfo is None: raise ValueError("use timezone-aware timestamps")
        if step <= timedelta(): raise ValueError("step must be positive")
        seen: set[str] = set(); outcomes: list[SignalOutcome] = []; now = start.astimezone(timezone.utc)
        while now <= end:
            self.provider.clock.set(now)
            for symbol in symbols:
                future = self._future_candles(symbol)
                for setup in self.scanner(symbol, self.provider):
                    fingerprint = getattr(setup, "fingerprint", str(getattr(setup, "setup_id", id(setup))))
                    if fingerprint in seen: continue
                    seen.add(fingerprint)
                    outcomes.append(evaluate_setup_outcome(setup, future, max_bars=self.max_bars, fee_slippage_r=self.fee_slippage_r))
            now += step
        return SignalBacktestResult(run_id, tuple(outcomes), calculate_metrics(outcomes))

    def _future_candles(self, symbol: str) -> tuple[Candle, ...]:
        # Repository access is deliberate here: outcome evaluation receives future bars,
        # but scanner invocation above only sees provider data at the historical clock.
        repo = self.provider.repository
        return tuple(repo.fetch_candles(symbol, "1m", self.provider.clock.now_ms + 1, 2**63 - 1))
