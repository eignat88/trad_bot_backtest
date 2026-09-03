"""Independent post-signal market-path outcomes (not dependent on TP/SL logic)."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

from app.data.historical_provider import Candle


@dataclass(frozen=True)
class SignalPathOutcome:
    """Future path measured from signal close, normalized by planned setup risk."""
    return_5m: float | None; return_15m: float | None; return_30m: float | None; return_1h: float | None
    return_4h: float | None; return_12h: float | None; return_24h: float | None
    mfe_15m_r: float | None; mfe_1h_r: float | None; mfe_4h_r: float | None; mfe_24h_r: float | None
    mae_15m_r: float | None; mae_1h_r: float | None; mae_4h_r: float | None; mae_24h_r: float | None
    hit_05r: bool | None; hit_10r: bool | None; hit_15r: bool | None; hit_20r: bool | None; hit_stop_before_1r: bool | None
    time_to_05r_min: int | None; time_to_1r_min: int | None; time_to_stop_min: int | None

    def as_dict(self) -> dict[str, object]: return asdict(self)


def evaluate_signal_path(candles: Sequence[Candle], *, signal_time_ms: int, signal_close: float, direction: str,
                         risk_distance: float, stop_price: float,
                         horizons_minutes: Iterable[int] = (5, 15, 30, 60, 240, 720, 1440)) -> SignalPathOutcome:
    """Measure only ``signal_time < candle_time <= signal_time + horizon``.

    Input may contain arbitrary candle history; pre-signal bars are ignored. Missing
    data leaves the corresponding horizon metric as ``None`` rather than silently
    evaluating a longer path. MFE is always non-negative and MAE non-positive.
    """
    if direction not in {"LONG", "SHORT"}: raise ValueError("direction must be LONG or SHORT")
    if signal_close <= 0 or risk_distance <= 0: raise ValueError("signal_close and risk_distance must be positive")
    requested = set(horizons_minutes)
    if not requested or any(minutes <= 0 for minutes in requested): raise ValueError("horizons must be positive")
    max_horizon = max(requested)
    future = sorted((c for c in candles if signal_time_ms < c.timestamp <= signal_time_ms + max_horizon * 60_000), key=lambda c: c.timestamp)

    def signed(price: float) -> float:
        raw = (price - signal_close) / risk_distance
        return raw if direction == "LONG" else -raw

    returns = {value: None for value in requested}; metrics = {value: None for value in (15, 60, 240, 1440)}
    max_favorable = max_adverse = 0.0; time_05 = time_1 = time_stop = None
    stop_before_1r: bool | None = None; stop_seen = target_seen = False
    for candle in future:
        elapsed = (candle.timestamp - signal_time_ms) // 60_000
        favorable = signed(candle.high if direction == "LONG" else candle.low)
        adverse = signed(candle.low if direction == "LONG" else candle.high)
        max_favorable, max_adverse = max(max_favorable, favorable), min(max_adverse, adverse)
        touches_stop = candle.low <= stop_price if direction == "LONG" else candle.high >= stop_price
        if touches_stop and time_stop is None: time_stop, stop_seen = elapsed, True
        if max_favorable >= .5 and time_05 is None: time_05 = elapsed
        if max_favorable >= 1 and time_1 is None: time_1, target_seen = elapsed, True
        if stop_before_1r is None and (stop_seen or target_seen): stop_before_1r = stop_seen  # conservative same-bar precedence
        if elapsed in returns: returns[elapsed] = round(signed(candle.close), 6)
        if elapsed in metrics: metrics[elapsed] = (round(max_favorable, 6), round(max_adverse, 6))

    def value(minutes: int) -> float | None: return returns.get(minutes)
    def mfe(minutes: int) -> float | None: return metrics[minutes][0] if metrics.get(minutes) else None
    def mae(minutes: int) -> float | None: return metrics[minutes][1] if metrics.get(minutes) else None
    has_path = bool(future)
    return SignalPathOutcome(value(5), value(15), value(30), value(60), value(240), value(720), value(1440),
        mfe(15), mfe(60), mfe(240), mfe(1440), mae(15), mae(60), mae(240), mae(1440),
        (max_favorable >= .5) if has_path else None, (max_favorable >= 1) if has_path else None,
        (max_favorable >= 1.5) if has_path else None, (max_favorable >= 2) if has_path else None,
        stop_before_1r, time_05, time_1, time_stop)
