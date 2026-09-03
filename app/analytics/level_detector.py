"""Re-derive which liquidity level was swept for attribution analysis.

Production LiquidityReversalScanner iterates over significant levels and
picks the first one swept by a recent 5m candle.  This module replicates
that logic so we can label each setup with its level type without modifying
the production scanner.

This module accepts swing-engine callables as parameters to avoid a hard
dependency on the production scanner package at import time.
"""
from __future__ import annotations


def detect_swept_level_type(
    *,
    direction: str,
    candles_5m: list,
    candles_15m: list,
    levels,
    swing_lookback: int = 5,
    sweep_margin: float = 0.001,
    find_swing_highs=None,
    find_swing_lows=None,
) -> str:
    """Return the type of level that was swept: swing, day, week, or unknown."""
    if find_swing_highs is None or find_swing_lows is None:
        return "unknown"

    if direction == "LONG":
        swing_points = find_swing_lows(candles_15m, swing_lookback)
        if not swing_points:
            return "unknown"
        significant_levels = [("swing_low", swing_points[-1].price)]
        if levels.previous_day_low > 0:
            significant_levels.append(("previous_day_low", levels.previous_day_low))
        if levels.previous_week_low > 0:
            significant_levels.append(("previous_week_low", levels.previous_week_low))
        for level_type, level_price in significant_levels:
            for c in candles_5m[-8:]:
                if c.low < level_price * (1 - sweep_margin):
                    return level_type
    else:
        swing_points = find_swing_highs(candles_15m, swing_lookback)
        if not swing_points:
            return "unknown"
        significant_levels = [("swing_high", swing_points[-1].price)]
        if levels.previous_day_high > 0:
            significant_levels.append(("previous_day_high", levels.previous_day_high))
        if levels.previous_week_high > 0:
            significant_levels.append(("previous_week_high", levels.previous_week_high))
        for level_type, level_price in significant_levels:
            for c in candles_5m[-8:]:
                if c.high > level_price * (1 + sweep_margin):
                    return level_type
    return "unknown"
