"""Quick diagnostic of edge backfill state across all symbols."""
from __future__ import annotations
import os
from pg8000 import dbapi

def main():
    conn = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), database="trad_bot_backtest")
    cur = conn.cursor()
    try:
        # Total setups
        cur.execute("SELECT count(*) FROM bt.setup")
        total = cur.fetchone()[0]
        print(f"Total bt.setup: {total:,}")

        # By symbol
        cur.execute("SELECT symbol, count(*) FROM bt.setup GROUP BY symbol ORDER BY count(*) DESC")
        print(f"\n{'Symbol':<15} {'Setups':>8} {'Features':>10} {'Outcomes':>10} {'Feature%':>10} {'Outcome%':>10}")
        print("-" * 75)
        for symbol, count in cur.fetchall():
            cur.execute("SELECT count(*) FROM dds.setup_feature_snapshot f JOIN bt.setup s ON s.id=f.setup_id WHERE s.symbol=%s", (symbol,))
            feat = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM dds.signal_outcome o JOIN bt.setup s ON s.id=o.setup_id WHERE s.symbol=%s", (symbol,))
            outc = cur.fetchone()[0]
            print(f"{symbol:<15} {count:>8,} {feat:>10,} {outc:>10,} {feat/count*100:>9.1f}% {outc/count*100:>9.1f}%")

        # Overall
        cur.execute("SELECT count(DISTINCT setup_id) FROM dds.setup_feature_snapshot")
        feat_total = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT setup_id) FROM dds.signal_outcome")
        outc_total = cur.fetchone()[0]
        print("-" * 75)
        print(f"{'TOTAL':<15} {total:>8,} {feat_total:>10,} {outc_total:>10,} {feat_total/total*100:>9.1f}% {outc_total/total*100:>9.1f}%")

        # Confluence
        cur.execute("SELECT count(*) FROM dds.setup_confluence")
        conf = cur.fetchone()[0]
        print(f"\nConfluence rows: {conf:,}")

        # Market context
        cur.execute("SELECT count(*) FROM dds.market_context_snapshot")
        ctx = cur.fetchone()[0]
        print(f"Market context snapshots: {ctx:,}")

    finally:
        cur.close(); conn.close()

if __name__ == "__main__":
    main()
