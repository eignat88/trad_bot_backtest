"""Pure point-in-time technical feature calculations for historical backfills."""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Sequence

from app.data.historical_provider import Candle


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period: return None
    value = sum(values[:period]) / period; alpha = 2 / (period + 1)
    for item in values[period:]: value = alpha * item + (1 - alpha) * value
    return value


def _atr(candles: Sequence[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1: return None
    tr = [max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)) for p, c in zip(candles[-period-1:-1], candles[-period:])]
    return sum(tr) / len(tr)


def _rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) < period + 1: return None
    changes = [closes[i] - closes[i - 1] for i in range(-period, 0)]
    gain, loss = sum(max(x, 0) for x in changes) / period, sum(max(-x, 0) for x in changes) / period
    if loss == 0: return 100.0
    return 100 - 100 / (1 + gain / loss)


def _adx(candles: Sequence[Candle], period: int = 14) -> float | None:
    if len(candles) < period + 1: return None
    plus, minus, trs = [], [], []
    for previous, current in zip(candles[-period-1:-1], candles[-period:]):
        up, down = current.high - previous.high, previous.low - current.low
        plus.append(max(up, 0) if up > down else 0); minus.append(max(down, 0) if down > up else 0)
        trs.append(max(current.high-current.low, abs(current.high-previous.close), abs(current.low-previous.close)))
    total_tr = sum(trs)
    if total_tr == 0: return 0.0
    pdi, mdi = 100 * sum(plus) / total_tr, 100 * sum(minus) / total_tr
    return 0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi)


def calculate_features(candles: Sequence[Candle], *, direction: str, scanner_score: float | None,
                       entry: float | None, stop: float | None, target: float | None) -> dict[str, float | int | None]:
    """Calculate only from sorted candles already observable at the signal timestamp."""
    if not candles: return {}
    rows = sorted(candles, key=lambda c: c.timestamp); closes = [c.close for c in rows]; volumes = [c.volume for c in rows]; last = rows[-1]
    ema20, ema50, ema200 = (_ema(closes, n) for n in (20, 50, 200))
    rsi = _rsi(closes); prior_rsi = _rsi(closes[:-3]) if len(closes) > 17 else None
    macd_fast, macd_slow = _ema(closes, 12), _ema(closes, 26)
    macd_series = [(_ema(closes[:i], 12) or 0) - (_ema(closes[:i], 26) or 0) for i in range(26, len(closes)+1)]
    signal = _ema(macd_series, 9); macd_hist = (macd_fast - macd_slow - signal) if macd_fast is not None and macd_slow is not None and signal is not None else None
    prior_hist = None
    if len(closes) > 3:
        pf, ps = _ema(closes[:-3], 12), _ema(closes[:-3], 26)
        seq = [(_ema(closes[:-3][:i], 12) or 0) - (_ema(closes[:-3][:i], 26) or 0) for i in range(26, len(closes[:-3])+1)]
        psg = _ema(seq, 9); prior_hist = (pf-ps-psg) if pf is not None and ps is not None and psg is not None else None
    atr = _atr(rows); atr_pct = atr / last.close * 100 if atr and last.close else None
    true_ranges = [_atr(rows[:i]) for i in range(15, len(rows)+1)]
    atr_percentile = (sum(x <= atr for x in true_ranges if x is not None) / len(true_ranges) * 100) if atr and true_ranges else None
    window20 = closes[-20:]; std20 = pstdev(window20) if len(window20) == 20 else None
    bb_width = (4 * std20 / mean(window20) * 100) if std20 is not None and mean(window20) else None
    log_returns = [math.log(closes[i]/closes[i-1]) for i in range(max(1, len(closes)-60), len(closes)) if closes[i-1] > 0]
    realized_vol = pstdev(log_returns) * math.sqrt(365*24*60) if len(log_returns) > 1 else None
    avg_volume = mean(volumes[-21:-1]) if len(volumes) >= 21 else None
    vol_std = pstdev(volumes[-21:-1]) if len(volumes) >= 21 else None
    body = abs(last.close-last.open); range_ = last.high-last.low
    upper = last.high-max(last.open,last.close); lower = min(last.open,last.close)-last.low
    high20, low20 = max(c.high for c in rows[-20:]), min(c.low for c in rows[-20:])
    def distance(level: float) -> float | None: return abs(last.close-level)/atr if atr and atr > 0 else None
    risk = abs(entry-stop) if entry is not None and stop is not None else None
    return {
        "ema20_distance_pct": (last.close/ema20-1)*100 if ema20 else None, "ema50_distance_pct": (last.close/ema50-1)*100 if ema50 else None,
        "ema200_distance_pct": (last.close/ema200-1)*100 if ema200 else None,
        "ema20_slope": ((_ema(closes[:-3],20) and ema20/_ema(closes[:-3],20)-1)*100) if ema20 and len(closes)>22 else None,
        "ema50_slope": ((_ema(closes[:-3],50) and ema50/_ema(closes[:-3],50)-1)*100) if ema50 and len(closes)>52 else None,
        "adx": _adx(rows), "trend_strength": _adx(rows), "rsi_14": rsi, "rsi_delta_3": rsi-prior_rsi if rsi is not None and prior_rsi is not None else None,
        "macd_hist": macd_hist, "macd_hist_delta": macd_hist-prior_hist if macd_hist is not None and prior_hist is not None else None,
        "roc_5": (last.close/closes[-6]-1)*100 if len(closes)>5 else None, "roc_20": (last.close/closes[-21]-1)*100 if len(closes)>20 else None,
        "atr_pct": atr_pct, "atr_percentile_30d": atr_percentile, "bb_width": bb_width, "bb_width_percentile": None, "realized_volatility": realized_vol,
        "volume_ratio_20": last.volume/avg_volume if avg_volume else None, "volume_zscore": (last.volume-avg_volume)/vol_std if vol_std else None,
        "quote_volume": last.volume*last.close, "body_pct": body/range_*100 if range_ else None, "upper_wick_pct": upper/range_*100 if range_ else None,
        "lower_wick_pct": lower/range_*100 if range_ else None, "distance_to_support_atr": distance(low20), "distance_to_resistance_atr": distance(high20),
        "range_position": (last.close-low20)/(high20-low20) if high20 > low20 else None, "scanner_score": scanner_score,
        "risk_distance_atr": risk/atr if risk and atr else None, "target_distance_atr": abs(target-entry)/atr if target and entry and atr else None,
        "rr_planned": abs(target-entry)/risk if target and entry and risk else None, "hour_of_day": (last.timestamp // 3_600_000) % 24,
        "day_of_week": None,
    }
