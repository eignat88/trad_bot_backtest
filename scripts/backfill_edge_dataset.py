"""Memory-efficient backfill of edge-research tables from bt.setup + market.candle.

Key design choices:
- Streaming candle fetch via server-side cursor (no fetchall on millions of rows)
- Sequential symbol processing (one symbol at a time, one batch at a time)
- Only load candles for the current batch's time window
- Single DB connection per symbol worker
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from pg8000 import dbapi

from app.data.historical_provider import Candle
from app.edge_research.features import calculate_features
from app.edge_research.outcomes import evaluate_signal_path

FEATURE_COLUMNS = (
    "ema20_distance_pct ema50_distance_pct ema200_distance_pct ema20_slope ema50_slope adx trend_strength "
    "rsi_14 rsi_delta_3 macd_hist macd_hist_delta roc_5 roc_20 atr_pct atr_percentile_30d bb_width bb_width_percentile "
    "realized_volatility volume_ratio_20 volume_zscore quote_volume body_pct upper_wick_pct lower_wick_pct "
    "distance_to_support_atr distance_to_resistance_atr range_position scanner_score risk_distance_atr target_distance_atr "
    "rr_planned confirmation_count hour_of_day day_of_week"
).split()

# How many days of 1m candles to pre-load per batch window.
# At 1440 candles/day, 7 days = ~10K rows ≈ ~1 MB.
CANDLE_LOOKBACK_DAYS = 7
CANDLE_FUTURE_DAYS = 2  # enough for 24h outcome + buffer


def connect(db_name: str):
    return dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database=db_name,
    )


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def as_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def candle_index(candles: list[Candle], at_ms: int) -> int:
    return bisect.bisect_right(candles, at_ms, key=lambda c: c.timestamp)


def slice_at(candles: list[Candle], at_ms: int, *, future: bool = False, limit: int | None = None) -> list[Candle]:
    index = candle_index(candles, at_ms)
    if future:
        return candles[index:index + limit] if limit else candles[index:]
    start = max(0, index - limit) if limit else 0
    return candles[start:index]


def payload_levels(payload: object) -> tuple[float | None, float | None, float | None, float | None]:
    if isinstance(payload, str):
        payload = json.loads(payload)
    payload = payload or {}
    return (
        as_float(payload.get("entry_zone_high") or payload.get("entry_zone_low")),
        as_float(payload.get("invalidation_price")),
        as_float(payload.get("target_1")),
        as_float(payload.get("target_2")),
    )


def pct_return(candles: list[Candle], at_ms: int, lookback_minutes: int) -> float | None:
    current_index = candle_index(candles, at_ms)
    past_index = candle_index(candles, at_ms - lookback_minutes * 60_000)
    if current_index == 0 or past_index == 0 or candles[past_index - 1].close == 0:
        return None
    return (candles[current_index - 1].close / candles[past_index - 1].close - 1) * 100


# ---------------------------------------------------------------------------
# Memory-efficient candle loading (streaming, not fetchall)
# ---------------------------------------------------------------------------

def load_candles_window(cursor, symbol: str, window_start: datetime, window_end: datetime) -> list[Candle]:
    """Load only 1m candles for one symbol within a narrow time window.

    Uses fetchmany() to avoid loading millions of rows at once.
    Typical window: ~7 days ≈ 10K rows ≈ 1 MB.
    """
    cursor.execute(
        """SELECT EXTRACT(EPOCH FROM c.open_time)*1000, c.open, c.high, c.low, c.close, c.volume
           FROM market.candle c JOIN market.instrument i ON i.id=c.instrument_id
           WHERE i.symbol=%s AND c.timeframe='1m' AND c.open_time>=%s AND c.open_time<=%s
           ORDER BY c.open_time""",
        (symbol, window_start, window_end),
    )
    candles: list[Candle] = []
    while True:
        rows = cursor.fetchmany(5000)
        if not rows:
            break
        for row in rows:
            candles.append(Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])))
    return candles


# ---------------------------------------------------------------------------
# DB writers (each call runs in its own connection)
# ---------------------------------------------------------------------------

def upsert_context(cursor, *, at: datetime, context: dict) -> str:
    ident = str(uuid5(NAMESPACE_URL, f"edge-backfill-v1:{at.isoformat()}"))
    cursor.execute(
        """INSERT INTO dds.market_context_snapshot
           (id,snapshot_time,btc_return_1h,btc_return_4h,market_breadth_1h,market_breadth_4h,
            median_alt_return_1h,cross_sectional_volatility,regime,regime_version)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (snapshot_time, regime_version) DO UPDATE SET
             id=EXCLUDED.id,
             btc_return_1h=EXCLUDED.btc_return_1h, btc_return_4h=EXCLUDED.btc_return_4h,
             market_breadth_1h=EXCLUDED.market_breadth_1h, market_breadth_4h=EXCLUDED.market_breadth_4h,
             median_alt_return_1h=EXCLUDED.median_alt_return_1h,
             cross_sectional_volatility=EXCLUDED.cross_sectional_volatility, regime=EXCLUDED.regime
           RETURNING id""",
        (ident, at, context["btc_return_1h"], context["btc_return_4h"], context["market_breadth_1h"],
         context["market_breadth_4h"], context["median_alt_return_1h"], context["cross_sectional_volatility"],
         context["regime"], context["regime_version"]),
    )
    return str(cursor.fetchone()[0])


def upsert_features(cursor, *, setup: dict, context_id: str, features: dict, raw_features: object) -> None:
    values = {key: features.get(key) for key in FEATURE_COLUMNS}
    values["day_of_week"] = setup["detected_at"].weekday()
    columns = ["setup_id", "market_context_id", "scanner_version", "feature_set_version", "signal_time", *FEATURE_COLUMNS, "features"]
    params = [
        setup["id"], context_id, setup["scanner_version"], "edge-backfill-v1", setup["detected_at"],
        *[values[key] for key in FEATURE_COLUMNS],
        json.dumps({"source_max_time": setup["detected_at"].isoformat(), "scanner_features": raw_features}, default=str),
    ]
    updates = ", ".join(f"{column}=EXCLUDED.{column}" for column in columns[1:])
    cursor.execute(
        f"INSERT INTO dds.setup_feature_snapshot ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))}) "
        f"ON CONFLICT (setup_id) DO UPDATE SET {updates}",
        params,
    )


def upsert_outcome(cursor, *, setup: dict, candles: list[Candle], entry: float, stop: float) -> bool:
    risk = abs(entry - stop)
    if risk <= 0:
        return False
    at_ms = int(setup["detected_at"].timestamp() * 1000)
    outcome = evaluate_signal_path(
        candles, signal_time_ms=at_ms, signal_close=entry,
        direction=setup["direction"], risk_distance=risk, stop_price=stop,
    )
    data = outcome.as_dict()
    columns = ["setup_id", "evaluated_at", *data]
    cursor.execute(
        f"INSERT INTO dds.signal_outcome ({', '.join(columns)}) "
        f"VALUES ({', '.join(['%s'] * len(columns))}) "
        f"ON CONFLICT (setup_id) DO UPDATE SET {', '.join(f'{key}=EXCLUDED.{key}' for key in columns[1:])}",
        [setup["id"], setup["detected_at"], *data.values()],
    )
    return data["return_1h"] is not None


# ---------------------------------------------------------------------------
# Single-symbol sequential processor (one DB connection, streaming loads)
# ---------------------------------------------------------------------------

def backfill_symbol(
    symbol: str,
    setups: list[dict],
    db_name: str,
    dry_run: bool,
    batch_size: int,
    counters: Counter,
):
    """Process all setups for one symbol, loading candles in small windows."""
    connection = connect(db_name)
    try:
        cursor = connection.cursor()
        try:
            if not setups:
                return

            # Sort setups by detected_at for sequential window processing
            sorted_setups = sorted(setups, key=lambda r: r["detected_at"])
            total = len(sorted_setups)

            for batch_start in range(0, total, batch_size):
                batch = sorted_setups[batch_start:batch_start + batch_size]
                batch_start_time = batch[0]["detected_at"]
                batch_end_time = batch[-1]["detected_at"]

                # Only load candles for this batch's time window (+ lookback)
                candle_start = batch_start_time - timedelta(days=CANDLE_LOOKBACK_DAYS)
                candle_end = batch_end_time + timedelta(days=CANDLE_FUTURE_DAYS)

                symbol_candles = load_candles_window(cursor, symbol, candle_start, candle_end)
                btc_candles = load_candles_window(cursor, "BTCUSDT", candle_start, candle_end)

                for setup in batch:
                    at_ms = int(setup["detected_at"].timestamp() * 1000)
                    history = slice_at(symbol_candles, at_ms, limit=1_500)
                    if len(history) < 200:
                        counters["skipped"] += 1
                        continue

                    payload = json.loads(setup["payload"]) if isinstance(setup["payload"], str) else (setup["payload"] or {})
                    entry, stop, target, _ = payload_levels(payload)
                    features = calculate_features(
                        history, direction=setup["direction"], scanner_score=as_float(setup["score"]),
                        entry=entry, stop=stop, target=target,
                    )

                    if dry_run:
                        counters["features"] += 1
                        continue

                    # Market context (from pre-loaded BTC candles)
                    btc_1h = pct_return(btc_candles, at_ms, 60)
                    btc_4h = pct_return(btc_candles, at_ms, 240)
                    regime = "UNKNOWN" if btc_4h is None else ("UP" if btc_4h > .25 else "DOWN" if btc_4h < -.25 else "RANGE")
                    ctx = {
                        "btc_return_1h": btc_1h, "btc_return_4h": btc_4h,
                        "market_breadth_1h": None, "market_breadth_4h": None,
                        "median_alt_return_1h": None, "cross_sectional_volatility": None,
                        "regime": regime, "regime_version": "edge-backfill-v1",
                    }
                    context_id = upsert_context(cursor, at=setup["detected_at"], context=ctx)
                    upsert_features(cursor, setup=setup, context_id=context_id, features=features, raw_features=payload.get("features", {}))

                    # Independent outcome
                    future = slice_at(symbol_candles, at_ms, future=True, limit=1_440)
                    has_outcome = entry is not None and stop is not None and upsert_outcome(
                        cursor, setup=setup, candles=future, entry=entry, stop=stop,
                    )

                    counters["features"] += 1
                    if has_outcome:
                        counters["outcomes"] += 1
                    else:
                        counters["outcome_incomplete"] += 1

                try:
                    connection.commit()
                except Exception as exc:
                    connection.rollback()
                    counters["errors"] += len(batch)
                    print(f"  [{symbol}] batch error: {type(exc).__name__}: {exc}", file=sys.stderr)

                processed = batch_start + len(batch)
                print(
                    f"  [{symbol}] {processed}/{total}  "
                    f"features={counters['features']}  outcomes={counters['outcomes']}  "
                    f"skipped={counters['skipped']}  errors={counters['errors']}",
                    flush=True,
                )
        finally:
            cursor.close()
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Memory-efficient backfill of edge-research tables")
    parser.add_argument("--from", dest="start")
    parser.add_argument("--to", dest="end")
    parser.add_argument("--scanner")
    parser.add_argument("--symbol")
    parser.add_argument("--limit", type=int, help="Maximum total setups; omit for all matching setups")
    parser.add_argument("--batch-size", type=int, default=200, help="Setups per batch (controls candle window size)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    args = parser.parse_args()

    if (args.limit is not None and args.limit <= 0) or args.batch_size <= 0:
        parser.error("--limit and --batch-size must be positive")

    # Phase 1: fetch all setups, grouped by symbol
    connection = connect(args.db_name)
    try:
        cursor = connection.cursor()
        try:
            where, values = ["1=1"], []
            if args.start:
                where.append("s.detected_at >= %s"); values.append(parse_time(args.start))
            if args.end:
                where.append("s.detected_at < %s"); values.append(parse_time(args.end))
            if args.scanner:
                where.append("s.scanner_name = %s"); values.append(args.scanner)
            if args.symbol:
                where.append("s.symbol = %s"); values.append(args.symbol.upper())
            limit_sql = ""
            if args.limit is not None:
                limit_sql = " LIMIT %s"; values.append(args.limit)
            cursor.execute(
                """SELECT s.id::text, s.symbol, s.direction, s.detected_at, s.score, s.payload, r.scanner_version
                   FROM bt.setup s JOIN bt.run r ON r.id=s.run_id
                   WHERE """ + " AND ".join(where) + " ORDER BY s.detected_at" + limit_sql, values)
            cols = [d[0] for d in cursor.description]
            all_setups = [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()
    finally:
        connection.close()

    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for s in all_setups:
        by_symbol[s["symbol"]].append(s)

    total = len(all_setups)
    n_symbols = len(by_symbol)
    dry = " (dry run)" if args.dry_run else ""
    print(f"Edge backfill{dry}")
    print(f"setups total: {total}  symbols: {n_symbols}")
    print(f"batch_size: {args.batch_size}  candle_window: {CANDLE_LOOKBACK_DAYS}d back + {CANDLE_FUTURE_DAYS}d forward")
    t0 = time.time()

    counters = Counter()

    # Sequential: one symbol at a time, one batch at a time
    for sym, sym_setups in sorted(by_symbol.items()):
        print(f"\n--- {sym}: {len(sym_setups)} setups ---", flush=True)
        backfill_symbol(sym, sym_setups, args.db_name, args.dry_run, args.batch_size, counters)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s")
    print(f"features written: {counters['features']}")
    print(f"outcomes written: {counters['outcomes']}")
    print(f"outcomes incomplete (no entry/stop): {counters.get('outcome_incomplete', 0)}")
    print(f"skipped insufficient history: {counters['skipped']}")
    print(f"errors: {counters['errors']}")
    return 1 if counters["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
