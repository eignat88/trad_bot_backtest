"""Fast signal-level setup outcome evaluator with conservative intrabar rules."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence
from app.data.historical_provider import Candle

OutcomeEvent = Literal["NO_ENTRY", "TP1", "TP2", "SL", "EXPIRED"]

class Setup(Protocol):
    setup_id: object; symbol: str; scanner_name: str; direction: str
    signal_candle_open_time: int; entry_zone_low: float; entry_zone_high: float
    invalidation_price: float; target_1: float; target_2: float | None

@dataclass(frozen=True)
class SignalOutcome:
    setup_id: str; symbol: str; scanner_name: str; direction: str
    entry_touched: bool; first_event: OutcomeEvent; result_r: float; mfe_r: float; mae_r: float
    bars_to_entry: int | None; bars_to_exit: int | None; entry_price: float | None; exit_price: float | None
    fee_slippage_adjusted_result_r: float


def evaluate_setup_outcome(setup: Setup, candles: Sequence[Candle], *, max_bars: int = 48, fee_slippage_r: float = 0.0) -> SignalOutcome:
    if max_bars <= 0: raise ValueError("max_bars must be positive")
    entry = setup.entry_zone_high if setup.direction == "LONG" else setup.entry_zone_low
    risk = abs(entry - setup.invalidation_price)
    if risk <= 0: raise ValueError("setup invalidation must differ from entry")
    future = [c for c in candles if c.timestamp > setup.signal_candle_open_time][:max_bars]
    entry_index = exit_index = None; exit_price = None; mfe = mae = 0.0; event: OutcomeEvent = "NO_ENTRY"
    for index, c in enumerate(future, 1):
        if entry_index is None:
            if not (c.low <= setup.entry_zone_high and c.high >= setup.entry_zone_low): continue
            entry_index = index
        if setup.direction == "LONG":
            mfe, mae = max(mfe, (c.high-entry)/risk), min(mae, (c.low-entry)/risk)
            if c.low <= setup.invalidation_price: event, exit_price = "SL", setup.invalidation_price
            elif setup.target_2 is not None and c.high >= setup.target_2: event, exit_price = "TP2", setup.target_2
            elif c.high >= setup.target_1: event, exit_price = "TP1", setup.target_1
        else:
            mfe, mae = max(mfe, (entry-c.low)/risk), min(mae, (entry-c.high)/risk)
            if c.high >= setup.invalidation_price: event, exit_price = "SL", setup.invalidation_price
            elif setup.target_2 is not None and c.low <= setup.target_2: event, exit_price = "TP2", setup.target_2
            elif c.low <= setup.target_1: event, exit_price = "TP1", setup.target_1
        if exit_price is not None: exit_index = index; break
    if entry_index is None: result = 0.0
    elif exit_price is None:
        event, exit_price, exit_index = "EXPIRED", (future[-1].close if future else entry), len(future)
        result = ((exit_price-entry) if setup.direction == "LONG" else (entry-exit_price)) / risk
    else: result = ((exit_price-entry) if setup.direction == "LONG" else (entry-exit_price)) / risk
    return SignalOutcome(str(setup.setup_id), setup.symbol, setup.scanner_name, setup.direction, entry_index is not None, event, round(result, 6), round(mfe, 6), round(mae, 6), entry_index, exit_index, entry if entry_index else None, exit_price, round(result-fee_slippage_r if entry_index else 0.0, 6))
