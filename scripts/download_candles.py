"""Download Binance Futures candles (15m, 1h) and upsert into PostgreSQL."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import urlopen, Request

from pg8000 import dbapi


BINANCE_KLINE_URL = "https://fapi.binance.com/fapi/v1/klines"

# Binance weight per request
TIMEFRAME_WEIGHT = {
    "1m": 1, "3m": 2, "5m": 2, "15m": 2,
    "30m": 5, "1h": 5, "2h": 10, "4h": 10,
}

# Milliseconds per candle
TIMEFRAME_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
}


def parse_range(value: str, *, is_end: bool) -> datetime:
    """Parse UTC ISO-8601 input; a date-only end is inclusive of that whole date."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if is_end and len(value) == 10:
        parsed += timedelta(days=1)
    return parsed


def fetch_batch(symbol: str, interval: str, start_ms: int, limit: int = 1500) -> list[list]:
    """Fetch a batch of klines from Binance Futures API."""
    params = urlencode({
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "limit": limit,
    })
    url = f"{BINANCE_KLINE_URL}?{params}"
    req = Request(url, headers={"User-Agent": "trad-bot-backtest/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def download_candles(
    symbol: str, timeframe: str, start: datetime, end: datetime
) -> list[list]:
    """Download all candle data for a symbol and timeframe within date range."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    
    all_candles: dict[int, list] = {}
    cursor = start_ms
    
    while cursor < end_ms:
        batch = fetch_batch(symbol, timeframe, cursor, limit=1500)
        if not batch:
            break
        
        for candle in batch:
            open_ms = int(candle[0])
            if open_ms >= end_ms:
                return [all_candles[k] for k in sorted(all_candles)]
            all_candles[open_ms] = candle
        
        # Next cursor: last open_time + 1ms
        cursor = int(batch[-1][0]) + 1
        
        # Rate limit: ~1200 weight/minute, sleep proportional to weight
        weight = TIMEFRAME_WEIGHT.get(timeframe, 5)
        sleep_time = weight / 1200 * 60 + 0.05
        time.sleep(sleep_time)
    
    return [all_candles[k] for k in sorted(all_candles)]


def upsert_candles(
    connection, symbol: str, exchange: str, timeframe: str, instrument_id: int, rows: list[list]
) -> int:
    """Upsert candle records into the database."""
    cursor = connection.cursor()
    try:
        values = [
            (
                instrument_id,
                timeframe,
                datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
                Decimal(row[1]),  # open
                Decimal(row[2]),  # high
                Decimal(row[3]),  # low
                Decimal(row[4]),  # close
                Decimal(row[5]),  # volume
                Decimal(row[6]),  # turnover (quote volume)
            )
            for row in rows
        ]
        cursor.executemany(
            """INSERT INTO market.candle
               (instrument_id, timeframe, open_time, open, high, low, close, volume, turnover)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (instrument_id, timeframe, open_time) DO UPDATE SET
                 open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                 close = EXCLUDED.close, volume = EXCLUDED.volume, turnover = EXCLUDED.turnover""",
            values,
        )
        connection.commit()
        return len(values)
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Binance Futures candles (15m/1h) into PostgreSQL"
    )
    parser.add_argument("--timeframes", nargs="+", default=["15m", "1h"],
                        choices=list(TIMEFRAME_MS.keys()),
                        help="Timeframes to download (default: 15m 1h)")
    parser.add_argument("--symbols", nargs="+",
                        help="Symbols to download. If omitted, all from market.instrument.")
    parser.add_argument("--start", default="2025-01-01",
                        help="Start date (YYYY-MM-DD or ISO-8601)")
    parser.add_argument("--end", default="2025-12-31",
                        help="End date (YYYY-MM-DD or ISO-8601)")
    parser.add_argument("--exchange", default="binance_futures",
                        help="Exchange name for instrument table (default: binance_futures)")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--db-user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--db-host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("PGPORT", "5432")))
    args = parser.parse_args()

    start = parse_range(args.start, is_end=False)
    end = parse_range(args.end, is_end=True)
    if start >= end:
        parser.error("--start must be before --end")

    connection = dbapi.connect(
        user=args.db_user,
        password=os.getenv("PGPASSWORD"),
        host=args.db_host,
        port=args.db_port,
        database=args.db_name,
    )
    try:
        cursor = connection.cursor()
        
        # Get instruments
        if args.symbols:
            placeholders = ",".join(["%s"] * len(args.symbols))
            cursor.execute(
                f"SELECT id, symbol FROM market.instrument WHERE symbol IN ({placeholders})",
                [s.upper() for s in args.symbols],
            )
        else:
            cursor.execute("SELECT id, symbol FROM market.instrument ORDER BY symbol")
        
        instruments = cursor.fetchall()
        cursor.close()
        
        if not instruments:
            print("No instruments found in market.instrument")
            return 1
        
        total_inserted = 0
        for timeframe in args.timeframes:
            print(f"\n=== Timeframe: {timeframe} ===")
            for instrument_id, symbol in instruments:
                print(f"[{symbol} {timeframe}] Fetching candles from {args.start} to {args.end}...")
                candles = download_candles(symbol, timeframe, start, end)
                if candles:
                    inserted = upsert_candles(
                        connection, symbol, args.exchange, timeframe, instrument_id, candles
                    )
                    total_inserted += inserted
                    print(f"[{symbol} {timeframe}] Fetched {len(candles)} candles, upserted {inserted}")
                else:
                    print(f"[{symbol} {timeframe}] No data found")
        
        print(f"\nTotal: {total_inserted} candles inserted")
    finally:
        connection.close()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
