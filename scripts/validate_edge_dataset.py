"""Database integrity gates required before edge discovery."""
from __future__ import annotations

import argparse
import os

from pg8000 import dbapi


CHECKS = {
    "Future leakage (snapshot time)": """SELECT count(*) FROM dds.setup_feature_snapshot f
        JOIN bt.setup s ON s.id = f.setup_id WHERE f.signal_time > s.detected_at""",
    "Outcome keys in features": """SELECT count(*) FROM dds.setup_feature_snapshot
        WHERE features ?| ARRAY['result_r','mfe_r','mae_r','return_1h','return_4h','return_24h','first_event']""",
    "MFE sign": """SELECT count(*) FROM dds.signal_outcome WHERE mfe_15m_r < 0 OR mfe_1h_r < 0 OR mfe_4h_r < 0 OR mfe_24h_r < 0""",
    "MAE sign": """SELECT count(*) FROM dds.signal_outcome WHERE mae_15m_r > 0 OR mae_1h_r > 0 OR mae_4h_r > 0 OR mae_24h_r > 0""",
    "Duplicate mart setup grain": """SELECT count(*) FROM (SELECT setup_id FROM mart.edge_dataset GROUP BY setup_id HAVING count(*) > 1) duplicates""",
}


def scalar(cursor, sql: str) -> int:
    cursor.execute(sql)
    return int(cursor.fetchone()[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate edge-research database integrity")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--min-coverage", type=float, default=.95, help="Minimum setup population required for features/outcomes")
    args = parser.parse_args()
    if not 0 < args.min_coverage <= 1: parser.error("--min-coverage must be in (0, 1]")
    connection = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), database=args.db_name)
    failed = False
    try:
        cursor = connection.cursor()
        try:
            print("EDGE DATASET INTEGRITY CHECK\n")
            cursor.execute("SELECT to_regclass('dds.setup_feature_snapshot'), to_regclass('dds.signal_outcome'), to_regclass('mart.edge_dataset')")
            if any(value is None for value in cursor.fetchone()):
                print("[FAIL] Research schema is not applied. Run app/db/schema.sql before validation.")
                return 2
            for label, sql in CHECKS.items():
                violations = scalar(cursor, sql)
                status = "PASS" if violations == 0 else "FAIL"
                print(f"[{status}] {label:.<38} {violations} violations")
                failed |= violations != 0
            cursor.execute("SELECT count(*) FROM bt.setup")
            total = int(cursor.fetchone()[0])
            for label, table in (("Feature population", "dds.setup_feature_snapshot"), ("Outcome population", "dds.signal_outcome")):
                cursor.execute(f"SELECT count(DISTINCT setup_id) FROM {table}")
                populated = int(cursor.fetchone()[0]); ratio = populated / total if total else 0.0
                status = "PASS" if total and ratio >= args.min_coverage else "FAIL"
                print(f"[{status}] {label:.<38} {populated:,} / {total:,} ({ratio:.1%})")
                failed |= status == "FAIL"
            for feature in ("rsi_14", "atr_pct", "volume_ratio_20", "ema20_slope"):
                cursor.execute(f"SELECT count(*), count(*) FILTER (WHERE {feature} IS NULL) FROM dds.setup_feature_snapshot")
                populated, missing = map(int, cursor.fetchone()); null_ratio = missing / populated if populated else 1.0
                status = "PASS" if populated and null_ratio <= (1 - args.min_coverage) else "FAIL"
                print(f"[{status}] NULL {feature:.<31} {missing:,} / {populated:,} ({null_ratio:.1%})")
                failed |= status == "FAIL"
            cursor.execute("SELECT count(*), count(DISTINCT setup_id) FROM mart.edge_dataset")
            rows, setups = cursor.fetchone()
            print(f"\nDataset: rows={rows} setups={setups} grain=one row per setup")
        finally:
            cursor.close()
    finally:
        connection.close()
    print("RESULT: " + ("NOT READY FOR EDGE DISCOVERY" if failed else "SAFE FOR EDGE DISCOVERY"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
