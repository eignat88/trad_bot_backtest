"""Discover and validate univariate conditional-edge candidates from mart.edge_dataset."""
from __future__ import annotations

import argparse
import os
from typing import Any

from pg8000 import dbapi

from app.edge_research.discovery import discover_univariate_edges, temporal_holdout


def fetch_rows(connection, *, scanner: str, direction: str) -> list[dict[str, Any]]:
    cursor = connection.cursor()
    try:
        clauses, values = ["scanner_name = %s", "result_r IS NOT NULL"], [scanner]
        if direction != "BOTH":
            clauses.append("direction = %s")
            values.append(direction)
        cursor.execute(
            "SELECT * FROM mart.edge_dataset WHERE " + " AND ".join(clauses) + " ORDER BY signal_time",
            values,
        )
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover point-in-time feature regions with positive conditional expectancy")
    parser.add_argument("--scanner", required=True)
    parser.add_argument("--direction", choices=("LONG", "SHORT", "BOTH"), default="BOTH")
    parser.add_argument("--feature", action="append", required=True, help="Numeric mart column; repeat for several features")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--bins", type=int, default=5)
    parser.add_argument("--min-samples", type=int, default=30)
    parser.add_argument("--holdout-fraction", type=float, default=.25)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    args = parser.parse_args()
    connection = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), database=args.db_name)
    try:
        rows = fetch_rows(connection, scanner=args.scanner, direction=args.direction)
    finally:
        connection.close()
    if len(rows) < 2:
        raise ValueError("at least two dated rows are required for chronological discovery/validation")
    discovery, validation = temporal_holdout(rows, holdout_fraction=args.holdout_fraction)
    if max(row["signal_time"] for row in discovery) >= min(row["signal_time"] for row in validation):
        raise RuntimeError("chronological split invariant violated")
    if {row["setup_id"] for row in discovery} & {row["setup_id"] for row in validation}:
        raise RuntimeError("setup overlap between discovery and validation")
    candidates = discover_univariate_edges(discovery, feature_names=args.feature, bins=args.bins,
        min_samples=args.min_samples, bootstrap_samples=args.bootstrap_samples, validation_rows=validation)
    print(f"Dataset: rows={len(rows)}")
    print(f"Discovery: {discovery[0]['signal_time']} -> {discovery[-1]['signal_time']} | setups={len(discovery)}")
    print(f"Validation: {validation[0]['signal_time']} -> {validation[-1]['signal_time']} | setups={len(validation)}")
    print("Overlap: setup_id=0 timestamps=0")
    print(f"scanner={args.scanner} direction={args.direction}")
    print("feature\trange\tsamples\tavg_r\tmedian_r\tpf\tP(avg_r>0)\tvalidation_avg_r\tvalidation_samples")
    for edge in candidates:
        upper = "+inf" if edge.upper == float("inf") else f"{edge.upper:.6g}"
        pf = "n/a" if edge.profit_factor is None else f"{edge.profit_factor:.3f}"
        validation_avg = "n/a" if edge.validation_avg_r is None else f"{edge.validation_avg_r:.4f}"
        print(f"{edge.feature}\t[{edge.lower:.6g}, {upper}]\t{edge.samples}\t{edge.avg_r:.4f}\t{edge.median_r:.4f}\t{pf}\t{edge.bootstrap_probability_positive:.1%}\t{validation_avg}\t{edge.validation_samples}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
