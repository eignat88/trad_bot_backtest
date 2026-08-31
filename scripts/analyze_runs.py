"""Print a compact analytical report for persisted backtest runs.

The report is intentionally SQL-backed so it validates what was persisted in
bt.run/bt.setup/bt.outcome, not only exported CSV files.
"""
from __future__ import annotations

import argparse
import os
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from pg8000 import dbapi


CONTROL_RUN_IDS = (
    "4572b486-41fd-4b64-8f75-a335996514a1",
    "fc274d7c-6051-4f3b-82a6-c66b0c6e2537",
)


def connect(db_name: str):
    return dbapi.connect(
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=db_name,
    )


def placeholders(values: Sequence[str]) -> str:
    if not values:
        raise ValueError("at least one run id is required")
    return ", ".join(["%s"] * len(values))


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(round(value, 6)).rstrip("0").rstrip(".")
    return str(value)


def print_table(title: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    materialized = [tuple(as_text(value) for value in row) for row in rows]
    widths = [len(column) for column in columns]
    for row in materialized:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    print(f"\n## {title}\n")
    print(" | ".join(column.ljust(width) for column, width in zip(columns, widths)))
    print(" | ".join("-" * width for width in widths))
    for row in materialized:
        print(" | ".join(value.ljust(width) for value, width in zip(row, widths)))


def fetch(cursor, sql: str, run_ids: Sequence[str]) -> tuple[list[str], list[tuple[Any, ...]]]:
    cursor.execute(sql.format(run_ids=placeholders(run_ids)), tuple(run_ids))
    return [item[0] for item in cursor.description], list(cursor.fetchall())


BASELINE_SQL = """
SELECT
    r.id::text AS run_id,
    s.scanner_name,
    s.direction,
    COUNT(o.*) AS outcomes,
    SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) AS entries,
    SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN o.result_r < 0 THEN 1 ELSE 0 END) AS losses,
    ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) AS avg_r_entry,
    ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 2) AS total_r_entries,
    ROUND(AVG(o.result_r)::numeric, 4) AS avg_r_setup,
    ROUND(SUM(o.result_r)::numeric, 2) AS total_r_all
FROM bt.run r
JOIN bt.setup s ON s.run_id = r.id
JOIN bt.outcome o ON o.setup_id = s.id
WHERE r.id IN ({run_ids})
GROUP BY r.id, s.scanner_name, s.direction
ORDER BY s.direction
"""

REGIME_SQL = """
SELECT
    s.direction,
    s.regime AS market_regime,
    COUNT(*) AS setups,
    SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) AS entries,
    SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN o.result_r < 0 THEN 1 ELSE 0 END) AS losses,
    ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) AS avg_r_entry,
    ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 2) AS total_r_entries,
    ROUND(AVG(o.result_r)::numeric, 4) AS avg_r_setup,
    ROUND(SUM(o.result_r)::numeric, 2) AS total_r_all
FROM bt.run r
JOIN bt.setup s ON s.run_id = r.id
JOIN bt.outcome o ON o.setup_id = s.id
WHERE r.id IN ({run_ids})
GROUP BY s.direction, s.regime
ORDER BY s.direction, total_r_all DESC
"""

SCORE_SQL = """
SELECT
    s.direction,
    CASE
        WHEN s.score < 30 THEN '<30'
        WHEN s.score < 40 THEN '30-39'
        WHEN s.score < 50 THEN '40-49'
        WHEN s.score < 60 THEN '50-59'
        ELSE '60+'
    END AS score_bucket,
    COUNT(*) AS setups,
    SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) AS entries,
    SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN o.result_r < 0 THEN 1 ELSE 0 END) AS losses,
    ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) AS avg_r_entry,
    ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 2) AS total_r_entries,
    ROUND(AVG(o.result_r)::numeric, 4) AS avg_r_setup,
    ROUND(SUM(o.result_r)::numeric, 2) AS total_r_all
FROM bt.run r
JOIN bt.setup s ON s.run_id = r.id
JOIN bt.outcome o ON o.setup_id = s.id
WHERE r.id IN ({run_ids})
GROUP BY s.direction, score_bucket
ORDER BY s.direction, score_bucket
"""

EVENT_SQL = """
SELECT
    s.direction,
    o.first_event,
    COUNT(*) AS setups,
    ROUND(AVG(o.result_r)::numeric, 4) AS avg_r_setup,
    ROUND(SUM(o.result_r)::numeric, 2) AS total_r_all
FROM bt.run r
JOIN bt.setup s ON s.run_id = r.id
JOIN bt.outcome o ON o.setup_id = s.id
WHERE r.id IN ({run_ids})
GROUP BY s.direction, o.first_event
ORDER BY s.direction, setups DESC
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze persisted backtest run ids")
    parser.add_argument("--run-id", action="append", help="Backtest run UUID; repeatable. Defaults to control LONG/SHORT runs")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    args = parser.parse_args()

    run_ids = tuple(args.run_id or CONTROL_RUN_IDS)
    connection = connect(args.db_name)
    try:
        cursor = connection.cursor()
        try:
            print(f"# Backtest analytical report\n\nRun ids: {', '.join(run_ids)}")
            for title, sql in (
                ("Baseline", BASELINE_SQL),
                ("By market regime", REGIME_SQL),
                ("By score bucket", SCORE_SQL),
                ("By first event", EVENT_SQL),
            ):
                columns, rows = fetch(cursor, sql, run_ids)
                print_table(title, columns, rows)
        finally:
            cursor.close()
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
