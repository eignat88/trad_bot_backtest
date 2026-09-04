"""Download Binance Futures funding rate data and upsert into PostgreSQL."""
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


BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
RATE_LIMIT_DELAY = 0.1  # 100ms between requests (10 req/s limit)


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


def fetch_batch(symbol: str, start_ms: int, limit: int = 1000) -> list[dict]:
    """Fetch a batch of funding rate records from Binance Futures API."""
    params = urlencode({"symbol": symbol, "startTime": start_ms, "limit": limit})
    url = f"{BINANCE_FUNDING_URL}?{params}"
    req = Request(url, headers={"User-Agent": "trad-bot-backtest/1.0"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())


def download_funding_rate(
    symbol: str, start: datetime, end: datetime
) -> list[dict]:
    """Download all funding rate data for a symbol within date range."""
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    
    all_records: list[dict] = []
    cursor = start_ms
    
    while cursor < end_ms:
        batch = fetch_batch(symbol, cursor, limit=1000)
        if not batch:
            break
        
        for record in batch:
            ft = record["fundingTime"]
            if ft >= end_ms:
                return all_records
            all_records.append(record)
        
        # Next cursor: last funding time + 1ms
        cursor = batch[-1]["fundingTime"] + 1
        time.sleep(RATE_LIMIT_DELAY)
    
    return all_records


def upsert_funding_rates(connection, symbol: str, instrument_id: int, records: list[dict]) -> int:
    """Upsert funding rate records into the database."""
    cursor = connection.cursor()
    try:
        values = [
            (
                instrument_id,
                datetime.fromtimestamp(r["fundingTime"] / 1000, tz=timezone.utc),
                Decimal(r["fundingRate"]),
            )
            for r in records
        ]
        cursor.executemany(
            """INSERT INTO market.funding_rate (instrument_id, funding_time, funding_rate)
               VALUES (%s, %s, %s)
               ON CONFLICT (instrument_id, funding_time) DO UPDATE SET
                 funding_rate = EXCLUDED.funding_rate""",
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
        description="Download Binance Futures funding rate data into PostgreSQL"
    )
    parser.add_argument("--symbols", nargs="+", help="Symbols to download (e.g. BTCUSDT ETHUSDT). If omitted, all from market.instrument.")
    parser.add_argument("--start", default="2025-01-01", help="Start date (YYYY-MM-DD or ISO-8601)")
    parser.add_argument("--end", default="2025-12-31", help="End date (YYYY-MM-DD or ISO-8601)")
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
        for instrument_id, symbol in instruments:
            print(f"[{symbol}] Fetching funding rate from {args.start} to {args.end}...")
            records = download_funding_rate(symbol, start, end)
            if records:
                inserted = upsert_funding_rates(connection, symbol, instrument_id, records)
                total_inserted += inserted
                print(f"[{symbol}] Fetched {len(records)} records, upserted {inserted}")
            else:
                print(f"[{symbol}] No data found")
        
        print(f"\nTotal: {total_inserted} funding rate records inserted")
    finally:
        connection.close()
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
