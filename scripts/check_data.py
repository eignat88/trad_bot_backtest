"""Check available symbols and date ranges in the backtest database."""
import os
from pg8000 import dbapi

def main():
    conn = dbapi.connect(
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database="trad_bot_backtest",
    )
    cur = conn.cursor()

    # Check available symbols with 1m candle count
    cur.execute("""
        SELECT i.symbol, COUNT(*) as cnt, 
               MIN(c.open_time) as first_date, MAX(c.open_time) as last_date
        FROM market.candle c 
        JOIN market.instrument i ON i.id = c.instrument_id
        WHERE c.timeframe = '1m'
        GROUP BY i.symbol
        HAVING COUNT(*) > 10000
        ORDER BY cnt DESC
        LIMIT 30
    """)
    print("=== Top symbols by 1m candle count ===")
    print(f"{'Symbol':<20} {'Candles':>10} {'From':<22} {'To':<22}")
    for row in cur.fetchall():
        print(f"{row[0]:<20} {row[1]:>10} {str(row[2]):<22} {str(row[3]):<22}")

    # Check if MOMENTUM_EXHAUSTION has been tested before
    cur.execute("""
        SELECT r.scanner_version, r.execution_profile->>'scanner' as scanner_name,
               COUNT(*) as runs
        FROM bt.run r
        GROUP BY r.scanner_version, r.execution_profile->>'scanner'
        ORDER BY runs DESC
    """)
    print("\n=== Previous backtest runs ===")
    for row in cur.fetchall():
        print(f"  version={row[0]}, scanner={row[1]}, runs={row[2]}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
