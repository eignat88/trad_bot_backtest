"""Download Bybit candles and upsert them into the local PostgreSQL history store."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from pg8000 import dbapi

BYBIT_KLINE_URL = "https://api.bybit.com/v5/market/kline"
TIMEFRAME_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
BYBIT_INTERVAL = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D"}


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


def fetch_batch(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list[str]]:
    query = urlencode({"category": "linear", "symbol": symbol, "interval": interval, "start": start_ms, "end": end_ms - 1, "limit": 1000})
    with urlopen(f"{BYBIT_KLINE_URL}?{query}", timeout=30) as response:
        payload = json.load(response)
    if payload.get("retCode") != 0:
        raise RuntimeError(f"Bybit request failed: {payload.get('retCode')} {payload.get('retMsg')}")
    return payload["result"].get("list", [])


def download(symbol: str, timeframe: str, start: datetime, end: datetime) -> list[list[str]]:
    interval_ms = TIMEFRAME_MS[timeframe]
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    candles: dict[int, list[str]] = {}
    while cursor < end_ms:
        batch_end = min(cursor + interval_ms * 1000, end_ms)
        batch = fetch_batch(symbol, BYBIT_INTERVAL[timeframe], cursor, batch_end)
        for row in batch:
            open_ms = int(row[0])
            if cursor <= open_ms < end_ms:
                candles[open_ms] = row
        cursor = batch_end
    return [candles[key] for key in sorted(candles)]


def upsert_candles(connection, symbol: str, exchange: str, timeframe: str, rows: Iterable[list[str]]) -> int:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """INSERT INTO market.instrument (symbol, exchange) VALUES (%s, %s)
               ON CONFLICT (symbol) DO UPDATE SET exchange = EXCLUDED.exchange
               RETURNING id""",
            (symbol, exchange),
        )
        instrument_id = cursor.fetchone()[0]
        values = [
            (instrument_id, timeframe, datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
             Decimal(row[1]), Decimal(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), Decimal(row[6]))
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
    parser = argparse.ArgumentParser(description="Download Bybit historical candles into PostgreSQL")
    parser.add_argument("--exchange", choices=("bybit",), default="bybit")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--timeframe", choices=tuple(TIMEFRAME_MS), required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--db-user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--db-host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("PGPORT", "5432")))
    args = parser.parse_args()

    start, end = parse_range(args.start, is_end=False), parse_range(args.end, is_end=True)
    if start >= end:
        parser.error("--from must be before --to")
    connection = dbapi.connect(user=args.db_user, password=os.getenv("PGPASSWORD"), host=args.db_host, port=args.db_port, database=args.db_name)
    try:
        for symbol in args.symbols:
            rows = download(symbol.upper(), args.timeframe, start, end)
            inserted = upsert_candles(connection, symbol.upper(), args.exchange, args.timeframe, rows)
            print(f"{symbol.upper()} {args.timeframe}: upserted {inserted} candles")
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
