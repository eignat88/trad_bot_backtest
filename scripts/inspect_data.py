"""Print candle coverage and liquidity ranking for research preparation."""
from __future__ import annotations

import os

from pg8000 import dbapi


def main() -> None:
    connection = dbapi.connect(
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("PGDATABASE", "trad_bot_backtest"),
    )
    try:
        cursor = connection.cursor()
        cursor.execute(
            """SELECT i.symbol, min(c.open_time), max(c.open_time), count(*),
                      sum(c.turnover) AS turnover
                 FROM market.candle c
                 JOIN market.instrument i ON i.id = c.instrument_id
                WHERE c.timeframe = '1m'
                GROUP BY i.symbol
                ORDER BY turnover DESC NULLS LAST, i.symbol
                LIMIT 20"""
        )
        for row in cursor.fetchall():
            print(*row, sep=" | ")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
