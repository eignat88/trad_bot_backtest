"""Compute enriched research features for scanner setups.

Production scanners emit a compact feature dict.  This module augments it with
additional attributes useful for attribution analysis: ATR-normalized sweep
depth, close location, volume ratios, ATR percentile, realized volatility,
session buckets, EMA200 side, and (when BTC is in the universe) BTC regime
and recent returns.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _atr_percentile(closes: list[float], lookback: int = 100) -> float:
    """Percentile rank of the latest bar-to-bar change within recent history."""
    if len(closes) < lookback:
        return 0.5
    changes = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(-lookback, 0) if closes[i - 1] != 0]
    if not changes:
        return 0.5
    latest = changes[-1]
    rank = sum(1 for c in changes if c <= latest)
    return round(rank / len(changes), 4)


def _realized_volatility(closes: list[float], window: int = 60) -> float:
    """Annualized realized volatility over the last `window` bars."""
    if len(closes) < window + 1:
        return 0.0
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(-window, 0) if closes[i - 1] > 0]
    if len(returns) < 10:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(var) * math.sqrt(365 * 24 * 12), 6)  # annualize 5-min bars


def _volume_ratio(volume: float, recent_volumes: list[float], period: int = 20) -> float:
    """Volume / SMA(volume, period)."""
    if not recent_volumes or period <= 0:
        return 1.0
    sample = recent_volumes[-period:]
    avg = sum(sample) / len(sample)
    return round(volume / avg, 4) if avg > 0 else 1.0


def _close_location(open_: float, high: float, low: float, close: float) -> float:
    """Where close sits within the bar range: 0.0 = low, 1.0 = high."""
    rng = high - low
    if rng <= 0:
        return 0.5
    return round((close - low) / rng, 4)


def _session_bucket(hour_utc: int) -> str:
    """Map UTC hour to a rough trading session label."""
    if 0 <= hour_utc < 7:
        return "asia"
    if 7 <= hour_utc < 12:
        return "europe"
    if 12 <= hour_utc < 17:
        return "us"
    return "late_us"


def enrich_liquidity_reversal(
    *,
    production_features: dict,
    direction: str,
    entry_price: float,
    swept_level: float,
    invalidation_price: float,
    target_1: float,
    atr: float,
    market_regime: str | None,
    evaluated_at: datetime,
    candles_5m: list,
    candles_1h: list,
    btc_candles_5m: list | None = None,
    btc_regime: str | None = None,
) -> dict:
    """Build an enriched feature dict for a LIQUIDITY_REVERSAL setup.

    Production features are preserved; enriched fields are added under
    an ``enriched`` sub-dict for clean separation.
    """
    last_5m = candles_5m[-1] if candles_5m else None
    risk = abs(entry_price - invalidation_price)

    # --- level type ---
    levels = production_features.get("_levels_considered", [])
    level_type = production_features.get("_swept_level_type", "unknown")

    # --- sweep depth in ATR ---
    raw_sweep_pct = abs(entry_price - swept_level) / swept_level if swept_level > 0 else 0.0
    sweep_depth_atr = round(abs(entry_price - swept_level) / atr, 4) if atr > 0 else 0.0

    # --- close location ---
    if last_5m:
        close_loc = _close_location(last_5m.open, last_5m.high, last_5m.low, last_5m.close)
    else:
        close_loc = 0.5

    # --- wick ratios ---
    if last_5m:
        candle_range = last_5m.high - last_5m.low
        body = abs(last_5m.close - last_5m.open)
        if candle_range > 0 and body > 0:
            wick_body_ratio = round((candle_range - body) / body, 4)
            wick_range_ratio = round((candle_range - body) / candle_range, 4)
        else:
            wick_body_ratio = 0.0
            wick_range_ratio = 0.0
    else:
        wick_body_ratio = 0.0
        wick_range_ratio = 0.0

    # --- volume ratio ---
    vol = last_5m.volume if last_5m else 0.0
    recent_vols = [c.volume for c in candles_5m[-20:]] if candles_5m else []
    vol_ratio_20 = _volume_ratio(vol, recent_vols, 20)

    # --- ATR percentile (from 1h closes) ---
    h1_closes = [c.close for c in candles_1h] if candles_1h else []
    atr_pctile = _atr_percentile(h1_closes, lookback=100)

    # --- realized volatility from 5m closes ---
    c5_closes = [c.close for c in candles_5m] if candles_5m else []
    realized_vol = _realized_volatility(c5_closes, window=60)

    # --- EMA200 side ---
    ema200 = _safe_float(production_features.get("ema200")) if "ema200" in production_features else None
    ema200_side = None
    if ema200 is not None and ema200 > 0:
        ema200_side = "above" if entry_price > ema200 else "below"

    # --- session ---
    hour_utc = evaluated_at.hour
    session = _session_bucket(hour_utc)

    # --- BTC context ---
    btc_return_15m = None
    btc_regime_label = btc_regime
    if btc_candles_5m and len(btc_candles_5m) >= 4:
        btc_return_15m = round(
            (btc_candles_5m[-1].close - btc_candles_5m[-4].close) / btc_candles_5m[-4].close, 6
        ) if btc_candles_5m[-4].close > 0 else 0.0

    return {
        **production_features,
        "enriched": {
            "level_type": level_type,
            "sweep_depth_pct": round(raw_sweep_pct * 100, 4),
            "sweep_depth_atr": sweep_depth_atr,
            "close_location": close_loc,
            "wick_body_ratio": wick_body_ratio,
            "wick_range_ratio": wick_range_ratio,
            "volume_ratio_20": vol_ratio_20,
            "atr_percentile": atr_pctile,
            "realized_volatility": realized_vol,
            "ema200_side": ema200_side,
            "session": session,
            "hour_utc": hour_utc,
            "btc_return_15m": btc_return_15m,
            "btc_regime": btc_regime_label,
            "direction": direction,
            "entry_price": round(entry_price, 8),
            "swept_level": round(swept_level, 8),
            "atr": round(atr, 8),
            "risk": round(risk, 8),
        },
    }
