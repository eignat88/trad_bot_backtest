"""Quick check of backtest database structure and data availability."""
import os
from pg8000 import dbapi

def main():
    # Check trad_bot_backtest
    for db_name in ["trad_bot_backtest", "trad_bot"]:
        try:
            conn = dbapi.connect(
                user=os.getenv("PGUSER", "postgres"),
                password=os.getenv("PGPASSWORD"),
                host=os.getenv("PGHOST", "localhost"),
                port=int(os.getenv("PGPORT", "5432")),
                database=db_name,
            )
            cur = conn.cursor()
            print(f"\n=== Database: {db_name} ===")
            cur.execute("""SELECT schemaname, tablename FROM pg_tables 
                          WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                          ORDER BY schemaname, tablename""")
            for row in cur.fetchall():
                print(f"  {row[0]}.{row[1]}")
            
            # Check for market.candle
            try:
                cur.execute("SELECT COUNT(*) FROM market.candle")
                cnt = cur.fetchone()[0]
                print(f"  market.candle rows: {cnt}")
            except Exception:
                print("  market.candle: NOT FOUND")
            
            # Check for bt schema
            try:
                cur.execute("SELECT COUNT(*) FROM bt.run")
                cnt = cur.fetchone()[0]
                print(f"  bt.run rows: {cnt}")
            except Exception:
                print("  bt schema: NOT FOUND")
            
            cur.close()
            conn.close()
        except Exception as e:
            print(f"\n=== Database: {db_name} === ERROR: {e}")

if __name__ == "__main__":
    main()
