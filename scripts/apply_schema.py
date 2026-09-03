"""Apply the project's idempotent PostgreSQL schema without requiring psql."""
from __future__ import annotations

import os
from pathlib import Path

from pg8000 import dbapi


def main() -> int:
    sql = (Path(__file__).resolve().parents[1] / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    connection = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"), host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), database=os.getenv("PGDATABASE", "trad_bot_backtest"))
    try:
        cursor = connection.cursor()
        try:
            # schema.sql contains plain DDL only; pg8000 executes the statement batch atomically.
            cursor.execute(sql)
            connection.commit()
        finally:
            cursor.close()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print("Schema applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
