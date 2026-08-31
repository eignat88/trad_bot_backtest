"""Export persisted backtest runs to analysis-friendly CSV/JSON files."""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pg8000 import dbapi


DETAIL_COLUMNS = (
    "run_id",
    "scanner_version",
    "run_start_at",
    "run_end_at",
    "symbols",
    "setup_id",
    "detected_at",
    "month",
    "scanner_name",
    "symbol",
    "direction",
    "regime",
    "score",
    "entry_touched",
    "first_event",
    "result_r",
    "fee_slippage_adjusted_result_r",
    "mfe_r",
    "mae_r",
    "bars_to_entry",
    "bars_to_exit",
    "entry_zone_low",
    "entry_zone_high",
    "invalidation_price",
    "target_1",
    "target_2",
    "features_json",
)

SUMMARY_COLUMNS = (
    "run_id",
    "direction",
    "symbol",
    "regime",
    "month",
    "setups",
    "entries",
    "wins",
    "losses",
    "expired",
    "no_entry",
    "win_rate",
    "entry_rate",
    "avg_result_r",
    "total_result_r",
    "avg_adjusted_result_r",
    "total_adjusted_result_r",
    "avg_mfe_r",
    "avg_mae_r",
)


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def as_float(value: Any) -> float:
    return float(value) if value is not None else 0.0


def parse_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return json.loads(payload)
    return dict(payload)


def connect(db_name: str):
    return dbapi.connect(
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=db_name,
    )


def fetch_rows(connection, run_ids: list[str]) -> list[dict[str, Any]]:
    placeholders = ", ".join(["%s"] * len(run_ids))
    sql = f"""
        SELECT
            r.id AS run_id,
            r.scanner_version,
            r.start_at AS run_start_at,
            r.end_at AS run_end_at,
            r.symbols,
            s.id AS setup_id,
            s.detected_at,
            to_char(s.detected_at AT TIME ZONE 'UTC', 'YYYY-MM') AS month,
            s.scanner_name,
            s.symbol,
            s.direction,
            s.regime,
            s.score,
            s.payload,
            o.entry_touched,
            o.first_event,
            o.result_r,
            o.fee_slippage_adjusted_result_r,
            o.mfe_r,
            o.mae_r,
            o.bars_to_entry,
            o.bars_to_exit
        FROM bt.run r
        JOIN bt.setup s ON s.run_id = r.id
        JOIN bt.outcome o ON o.setup_id = s.id
        WHERE r.id IN ({placeholders})
        ORDER BY r.id, s.detected_at, s.symbol, s.direction, s.id
    """
    cursor = connection.cursor()
    try:
        cursor.execute(sql, run_ids)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def detail_record(row: dict[str, Any]) -> dict[str, Any]:
    payload = parse_payload(row.pop("payload", None))
    features = payload.get("features", {})
    record = dict(row)
    record.update(
        entry_zone_low=payload.get("entry_zone_low"),
        entry_zone_high=payload.get("entry_zone_high"),
        invalidation_price=payload.get("invalidation_price"),
        target_1=payload.get("target_1"),
        target_2=payload.get("target_2"),
        features_json=json.dumps(features, ensure_ascii=False, sort_keys=True, default=json_default),
    )
    return {column: record.get(column) for column in DETAIL_COLUMNS}


def summarize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (record["run_id"], record["direction"], record["symbol"], record["regime"], record["month"])
        groups[key].append(record)

    summary: list[dict[str, Any]] = []
    for key, items in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
        setups = len(items)
        entries = sum(1 for item in items if item["entry_touched"])
        wins = sum(1 for item in items if as_float(item["fee_slippage_adjusted_result_r"]) > 0)
        losses = sum(1 for item in items if as_float(item["fee_slippage_adjusted_result_r"]) < 0)
        expired = sum(1 for item in items if item["first_event"] == "EXPIRED")
        no_entry = sum(1 for item in items if item["first_event"] == "NO_ENTRY")
        total_r = sum(as_float(item["result_r"]) for item in items)
        total_adjusted_r = sum(as_float(item["fee_slippage_adjusted_result_r"]) for item in items)
        total_mfe = sum(as_float(item["mfe_r"]) for item in items)
        total_mae = sum(as_float(item["mae_r"]) for item in items)
        summary.append(
            dict(
                zip(("run_id", "direction", "symbol", "regime", "month"), key),
                setups=setups,
                entries=entries,
                wins=wins,
                losses=losses,
                expired=expired,
                no_entry=no_entry,
                win_rate=round(wins / entries, 6) if entries else 0.0,
                entry_rate=round(entries / setups, 6) if setups else 0.0,
                avg_result_r=round(total_r / setups, 6) if setups else 0.0,
                total_result_r=round(total_r, 6),
                avg_adjusted_result_r=round(total_adjusted_r / setups, 6) if setups else 0.0,
                total_adjusted_result_r=round(total_adjusted_r, 6),
                avg_mfe_r=round(total_mfe / setups, 6) if setups else 0.0,
                avg_mae_r=round(total_mae / setups, 6) if setups else 0.0,
            )
        )
    return summary


def write_csv(path: Path, columns: tuple[str, ...], records: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export bt.run/bt.setup/bt.outcome rows to CSV files")
    parser.add_argument("--run-id", action="append", required=True, help="Backtest run UUID; pass multiple times")
    parser.add_argument("--output-dir", default="exports", help="Directory for CSV/JSON exports")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_ids = [run_id.strip() for run_id in args.run_id]

    connection = connect(args.db_name)
    try:
        rows = fetch_rows(connection, run_ids)
    finally:
        connection.close()

    details = [detail_record(dict(row)) for row in rows]
    summary = summarize(details)
    suffix = "_".join(run_id[:8] for run_id in run_ids)
    detail_path = output_dir / f"backtest_details_{suffix}.csv"
    summary_path = output_dir / f"backtest_summary_{suffix}.csv"
    metadata_path = output_dir / f"backtest_export_{suffix}.json"

    write_csv(detail_path, DETAIL_COLUMNS, details)
    write_csv(summary_path, SUMMARY_COLUMNS, summary)
    metadata_path.write_text(
        json.dumps(
            {
                "run_ids": run_ids,
                "detail_csv": str(detail_path),
                "summary_csv": str(summary_path),
                "rows": len(details),
                "summary_rows": len(summary),
            },
            ensure_ascii=False,
            indent=2,
            default=json_default,
        ),
        encoding="utf-8",
    )

    print(f"details={detail_path} rows={len(details)}")
    print(f"summary={summary_path} rows={len(summary)}")
    print(f"metadata={metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
