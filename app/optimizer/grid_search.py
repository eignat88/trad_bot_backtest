"""Deterministic grid search; caller supplies a scanner factory per parameter set."""
from __future__ import annotations
from dataclasses import dataclass
from itertools import product
from typing import Any, Callable, Mapping
from app.analytics.metrics import composite_objective
from app.backtest.signal_backtest import SignalBacktest, SignalBacktestResult

@dataclass(frozen=True)
class OptimizationResult:
    parameters: dict[str, Any]; result: SignalBacktestResult; objective: float

def parameter_grid(space: Mapping[str, list[Any]]) -> tuple[dict[str, Any], ...]:
    names = tuple(space)
    return tuple(dict(zip(names, values)) for values in product(*(space[name] for name in names)))

class GridSearchOptimizer:
    def __init__(self, build_backtest: Callable[[dict[str, Any]], SignalBacktest], run_kwargs: dict[str, Any], *, minimum_trades: int = 100) -> None:
        self.build_backtest, self.run_kwargs, self.minimum_trades = build_backtest, run_kwargs, minimum_trades

    def optimize(self, space: Mapping[str, list[Any]]) -> tuple[OptimizationResult, ...]:
        results = []
        for index, parameters in enumerate(parameter_grid(space), 1):
            result = self.build_backtest(parameters).run(run_id=f"grid-{index:04d}", **self.run_kwargs)
            results.append(OptimizationResult(parameters, result, composite_objective(result.metrics, minimum_trades=self.minimum_trades)))
        return tuple(sorted(results, key=lambda item: item.objective, reverse=True))
