"""Run the production TREND_PULLBACK scanner against PostgreSQL historical candles."""
from __future__ import annotations

import argparse
import bisect
import json
from dataclasses import replace
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from pg8000 import dbapi


TIMEFRAME_INTERVAL_MS = {
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}


def parse_range(value: str, *, is_end: bool) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if is_end and len(value) == 10:
        parsed += timedelta(days=1)
    return parsed


def import_production_scanner(production_root: str):
    root = str(Path(production_root).resolve())
    if not (Path(root) / "app").is_dir():
        raise FileNotFoundError(f"production project not found: {root}")
    sys.path.insert(0, root)
    from app.models import Candle
    from app.scanners.context_builder import _build_indicators, _classify_market_regime
    from app.scanners.models import MarketContext, MarketLevels
    from app.scanners.trend_pullback import TrendPullbackScanner
    return Candle, _build_indicators, _classify_market_regime, MarketContext, MarketLevels, TrendPullbackScanner


def resample(candles, interval_ms: int, candle_type):
    buckets = {}
    for candle in candles:
        buckets.setdefault(candle.timestamp - candle.timestamp % interval_ms, []).append(candle)
    return tuple(
        candle_type(ts, group[0].open, max(c.high for c in group), min(c.low for c in group), group[-1].close, sum(c.volume for c in group))
        for ts, group in sorted(buckets.items())
        if len(group) == interval_ms // 60_000
    )


def finalized_candidate(candidate, *, signal_candle_open_time: int, detected_at: datetime):
    """Bind a production setup to the closed 5m candle that generated it.

    Production candidates are immutable and its live scanner currently leaves
    ``signal_candle_open_time`` at its default.  A deterministic identity is
    essential in historical mode, both for de-duplication and persistence.
    """
    return replace(
        candidate,
        signal_candle_open_time=signal_candle_open_time,
        detected_at=detected_at,
    )


def evaluate(candidate, future, *, max_bars: int = 48, target_r: float | None = None, expire_at_breakeven: bool = False):
    entry = candidate.entry_zone_high if candidate.direction == "LONG" else candidate.entry_zone_low
    risk = abs(entry - candidate.invalidation_price)
    if risk <= 0:
        raise ValueError("candidate has invalid risk")
    target_1 = candidate.target_1
    target_2 = candidate.target_2
    if target_r is not None:
        if candidate.direction == "LONG":
            target_1 = entry + risk * target_r
            target_2 = None
        else:
            target_1 = entry - risk * target_r
            target_2 = None
    entry_index = exit_index = None
    exit_price = None
    mfe = mae = 0.0
    event = "NO_ENTRY"
    evaluation_bars = min(len(future), max_bars)
    for index, candle in enumerate(future[:evaluation_bars], 1):
        if entry_index is None:
            if not (candle.low <= candidate.entry_zone_high and candle.high >= candidate.entry_zone_low):
                continue
            entry_index = index
        if candidate.direction == "LONG":
            mfe, mae = max(mfe, (candle.high - entry) / risk), min(mae, (candle.low - entry) / risk)
            if candle.low <= candidate.invalidation_price:
                event, exit_price = "SL", candidate.invalidation_price
            elif target_2 is not None and candle.high >= target_2:
                event, exit_price = "TP2", target_2
            elif candle.high >= target_1:
                event, exit_price = "TP1", target_1
        else:
            mfe, mae = max(mfe, (entry - candle.low) / risk), min(mae, (entry - candle.high) / risk)
            if candle.high >= candidate.invalidation_price:
                event, exit_price = "SL", candidate.invalidation_price
            elif target_2 is not None and candle.low <= target_2:
                event, exit_price = "TP2", target_2
            elif candle.low <= target_1:
                event, exit_price = "TP1", target_1
        if exit_price is not None:
            exit_index = index
            break
    if entry_index is None:
        return False, event, 0.0, 0.0, 0.0, None, None
    if exit_price is None:
        exit_index = evaluation_bars
        if expire_at_breakeven:
            event, exit_price = "EXPIRED_BE", entry
        else:
            event, exit_price = "EXPIRED", future[evaluation_bars - 1].close
    result = ((exit_price - entry) if candidate.direction == "LONG" else (entry - exit_price)) / risk
    return True, event, round(result, 6), round(mfe, 6), round(mae, 6), entry_index, exit_index


def load_candles(connection, symbol: str, start: datetime, end: datetime, candle_type):
    cursor = connection.cursor()
    try:
        cursor.execute("""SELECT EXTRACT(EPOCH FROM c.open_time) * 1000, c.open, c.high, c.low, c.close, c.volume
                          FROM market.candle c JOIN market.instrument i ON i.id = c.instrument_id
                          WHERE i.symbol = %s AND c.timeframe = '1m'
                            AND c.open_time >= %s AND c.open_time < %s ORDER BY c.open_time""", (symbol, start, end))
        return tuple(candle_type(int(row[0]), *map(float, row[1:])) for row in cursor.fetchall())
    finally:
        cursor.close()


def candidate_passes_filters(candidate, *, skip_range: bool = False, allowed_regimes: set[str] | None = None, max_pullback_quality: float | None = None, min_rsi_confirmation: float | None = None, max_rsi_confirmation: float | None = None) -> bool:
    """Apply research filters that reduce weak/noisy historical setups."""
    if allowed_regimes is not None and candidate.market_regime not in allowed_regimes:
        return False
    if skip_range and candidate.market_regime == "RANGE":
        return False
    features = candidate.features or {}
    pullback_quality = features.get("pullback_quality")
    if max_pullback_quality is not None and pullback_quality is not None and float(pullback_quality) > max_pullback_quality:
        return False
    rsi_confirmation = features.get("rsi_confirmation")
    if min_rsi_confirmation is not None and rsi_confirmation is not None and float(rsi_confirmation) < min_rsi_confirmation:
        return False
    if max_rsi_confirmation is not None and rsi_confirmation is not None and float(rsi_confirmation) > max_rsi_confirmation:
        return False
    return True


def persist(connection, run_id, version, start, end, symbols, candidates, outcomes, *, execution_profile: dict | None = None):
    cursor = connection.cursor()
    try:
        profile = execution_profile or {"engine": "signal-level", "max_bars": 48}
        cursor.execute("""INSERT INTO bt.run (id, scanner_version, execution_profile, start_at, end_at, symbols)
                          VALUES (%s, %s, %s::jsonb, %s, %s, %s::jsonb)""",
                       (str(run_id), version, json.dumps(profile), start, end, json.dumps(symbols)))
        for candidate, outcome in zip(candidates, outcomes):
            payload = {"entry_zone_low": candidate.entry_zone_low, "entry_zone_high": candidate.entry_zone_high,
                       "invalidation_price": candidate.invalidation_price, "target_1": candidate.target_1,
                       "target_2": candidate.target_2, "features": candidate.features}
            cursor.execute("""INSERT INTO bt.setup (id, run_id, scanner_name, symbol, direction, regime, score, detected_at, payload)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
                           (str(candidate.setup_id), str(run_id), candidate.scanner_name, candidate.symbol, candidate.direction,
                            candidate.market_regime, candidate.score, candidate.detected_at, json.dumps(payload, default=str)))
            cursor.execute("""INSERT INTO bt.outcome (setup_id, entry_touched, first_event, result_r, mfe_r, mae_r, bars_to_entry, bars_to_exit, fee_slippage_adjusted_result_r)
                              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                           (str(candidate.setup_id), *outcome, outcome[2]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a historical production scanner backtest")
    parser.add_argument("--scanner", required=True, choices=("TREND_PULLBACK",))
    parser.add_argument("--direction", required=True, choices=("LONG", "SHORT"))
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--production-root", default="../trad_bot")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--skip-range", action="store_true", help="Skip RANGE regime setups")
    parser.add_argument("--allowed-regime", action="append", help="Keep only this regime; pass multiple times for several regimes")
    parser.add_argument("--signal-timeframe", choices=tuple(TIMEFRAME_INTERVAL_MS), default="5m", help="Closed timeframe used as scanner trigger/pullback candles")
    parser.add_argument("--max-bars", type=int, default=48, help="Maximum 1m bars to evaluate after signal")
    parser.add_argument("--target-r", type=float, help="Override scanner target_1 with fixed R target from entry")
    parser.add_argument("--expire-at-breakeven", action="store_true", help="Close unresolved entries at 0R instead of last close")
    parser.add_argument("--max-pullback-quality", type=float, help="Keep only setups with pullback_quality <= this value")
    parser.add_argument("--min-rsi-confirmation", type=float, help="Keep only setups with rsi_confirmation >= this value")
    parser.add_argument("--max-rsi-confirmation", type=float, help="Keep only setups with rsi_confirmation <= this value")
    parser.add_argument("--pullback-tolerance", type=float, help="Override production scanner pullback_tolerance")
    parser.add_argument("--rsi-cool-threshold", type=float, help="Override production scanner rsi_cool_threshold")
    args = parser.parse_args()
    start, end = parse_range(args.start, is_end=False), parse_range(args.end, is_end=True)
    Candle, build_indicators, classify_regime, MarketContext, MarketLevels, Scanner = import_production_scanner(args.production_root)
    connection = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"), host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), database=args.db_name)
    try:
        all_candidates, all_outcomes = [], []
        for symbol in args.symbols:
            candles = load_candles(connection, symbol.upper(), start, end, Candle)
            if not candles:
                raise ValueError(f"no 1m candles for {symbol}")
            five, fifteen, hour, four_hour = (resample(candles, interval, Candle) for interval in (300_000, 900_000, 3_600_000, 14_400_000))
            timeframe_rows = {"5m": five, "15m": fifteen, "1h": hour, "4h": four_hour}
            timestamps = {tf: [c.timestamp for c in rows] for tf, rows in timeframe_rows.items()}
            signal_rows = timeframe_rows[args.signal_timeframe]
            signal_interval_ms = TIMEFRAME_INTERVAL_MS[args.signal_timeframe]
            minute_timestamps = [c.timestamp for c in candles]
            scanner_kwargs = {}
            if args.pullback_tolerance is not None:
                scanner_kwargs["pullback_tolerance"] = args.pullback_tolerance
            if args.rsi_cool_threshold is not None:
                scanner_kwargs["rsi_cool_threshold"] = args.rsi_cool_threshold
            scanner = Scanner(**scanner_kwargs)
            seen = set()
            for current in signal_rows:
                # A resampled signal candle is observable only after its final 1m bar
                # closes. Never let outcome evaluation use the 1m bars already
                # incorporated in this signal candle.
                closed_at_ms = current.timestamp + signal_interval_ms
                now = datetime.fromtimestamp(closed_at_ms / 1000, tz=timezone.utc)
                if now < start or now >= end:
                    continue
                windows = {}
                for tf, rows, interval_ms in (("5m", five, 300_000), ("15m", fifteen, 900_000), ("1h", hour, 3_600_000), ("4h", four_hour, 14_400_000)):
                    # A higher-timeframe OHLCV bar becomes observable only at
                    # its close, not at its bucket's opening timestamp.
                    end_index = bisect.bisect_right(timestamps[tf], closed_at_ms - interval_ms)
                    windows[tf] = rows[max(0, end_index - 200):end_index]
                if len(windows["1h"]) < 50 or len(windows["15m"]) < 30 or len(windows["5m"]) < 20:
                    continue
                indicators = build_indicators(list(windows["1h"]))
                signal_window = tuple(windows[args.signal_timeframe])
                context = MarketContext(symbol=symbol.upper(), candles_5m=signal_window, candles_15m=tuple(windows["15m"]), candles_1h=tuple(windows["1h"]), candles_4h=tuple(windows["4h"]), indicators=indicators, market_regime=classify_regime(indicators, windows["1h"][-1].close), levels=MarketLevels(), evaluated_at=now)
                future_index = bisect.bisect_left(minute_timestamps, closed_at_ms)
                for raw_candidate in scanner.scan(context):
                    candidate = finalized_candidate(
                        raw_candidate,
                        signal_candle_open_time=current.timestamp,
                        detected_at=now,
                    )
                    if candidate.direction != args.direction or candidate.fingerprint in seen:
                        continue
                    if not candidate_passes_filters(
                        candidate,
                        skip_range=args.skip_range,
                        allowed_regimes=set(args.allowed_regime) if args.allowed_regime else None,
                        max_pullback_quality=args.max_pullback_quality,
                        min_rsi_confirmation=args.min_rsi_confirmation,
                        max_rsi_confirmation=args.max_rsi_confirmation,
                    ):
                        continue
                    seen.add(candidate.fingerprint)
                    all_candidates.append(candidate)
                    all_outcomes.append(
                        evaluate(
                            candidate,
                            candles[future_index:],
                            max_bars=args.max_bars,
                            target_r=args.target_r,
                            expire_at_breakeven=args.expire_at_breakeven,
                        )
                    )
        run_id = uuid4()
        execution_profile = {
            "engine": "signal-level",
            "signal_timeframe": args.signal_timeframe,
            "max_bars": args.max_bars,
            "target_r": args.target_r,
            "expire_at_breakeven": args.expire_at_breakeven,
            "skip_range": args.skip_range,
            "allowed_regime": args.allowed_regime,
            "max_pullback_quality": args.max_pullback_quality,
            "min_rsi_confirmation": args.min_rsi_confirmation,
            "max_rsi_confirmation": args.max_rsi_confirmation,
            "pullback_tolerance": args.pullback_tolerance,
            "rsi_cool_threshold": args.rsi_cool_threshold,
        }
        persist(connection, run_id, Scanner.version, start, end, args.symbols, all_candidates, all_outcomes, execution_profile=execution_profile)
        total_r = sum(item[2] for item in all_outcomes)
        avg_r = total_r / len(all_outcomes) if all_outcomes else 0.0
        print(f"run_id={run_id} setups={len(all_outcomes)} avg_r={avg_r:.6f} total_r={total_r:.6f}")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
