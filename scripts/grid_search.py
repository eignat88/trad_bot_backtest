"""Automated grid search for TREND_PULLBACK scanner optimization.

Runs multiple backtest configurations in sequence, collecting results for comparison.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pg8000 import dbapi


@dataclass
class ParamSet:
    """One configuration to test."""
    label: str
    scanner_params: dict[str, Any] = field(default_factory=dict)
    backtest_params: dict[str, Any] = field(default_factory=dict)


def build_param_sets() -> list[ParamSet]:
    """Build the grid of parameter combinations to test."""
    sets = []

    # ── Baseline (production defaults) ──
    sets.append(ParamSet(
        label="baseline",
        backtest_params={"signal_timeframe": "5m", "max_bars": 48},
    ))

    # ── Phase 1: pullback_tolerance sweep ──
    for pt in [0.005, 0.008, 0.01, 0.012, 0.015, 0.02]:
        sets.append(ParamSet(
            label=f"pt_{pt}",
            scanner_params={"pullback_tolerance": pt},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48},
        ))

    # ── Phase 2: rsi_cool_threshold sweep ──
    for rct in [45, 50, 55, 60, 65]:
        sets.append(ParamSet(
            label=f"rct_{rct}",
            scanner_params={"rsi_cool_threshold": rct},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48},
        ))

    # ── Phase 3: signal_timeframe sweep ──
    for tf in ["5m", "15m"]:
        sets.append(ParamSet(
            label=f"tf_{tf}",
            scanner_params={"pullback_tolerance": 0.01, "rsi_cool_threshold": 55},
            backtest_params={"signal_timeframe": tf, "max_bars": 48},
        ))

    # ── Phase 4: target_r sweep ──
    for tr in [0.5, 0.75, 1.0, 1.5, 2.0]:
        sets.append(ParamSet(
            label=f"tr_{tr}",
            scanner_params={"pullback_tolerance": 0.01, "rsi_cool_threshold": 55},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48, "target_r": tr},
        ))

    # ── Phase 5: skip_range ──
    sets.append(ParamSet(
        label="skip_range",
        scanner_params={"pullback_tolerance": 0.01, "rsi_cool_threshold": 55},
        backtest_params={"signal_timeframe": "5m", "max_bars": 48, "skip_range": True},
    ))

    # ── Phase 6: max_pullback_quality filter ──
    for mpq in [0.5, 0.6, 0.7, 0.85]:
        sets.append(ParamSet(
            label=f"mpq_{mpq}",
            scanner_params={"pullback_tolerance": 0.01, "rsi_cool_threshold": 55},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48, "max_pullback_quality": mpq},
        ))

    # ── Phase 7: expire_at_breakeven ──
    sets.append(ParamSet(
        label="expire_be",
        scanner_params={"pullback_tolerance": 0.01, "rsi_cool_threshold": 55},
        backtest_params={"signal_timeframe": "5m", "max_bars": 48, "expire_at_breakeven": True},
    ))

    # ── Phase 8: combined best candidates ──
    # Narrow combos from Phase 1-7 analysis
    best_combos = [
        {"pullback_tolerance": 0.005, "rsi_cool_threshold": 50},
        {"pullback_tolerance": 0.008, "rsi_cool_threshold": 50},
        {"pullback_tolerance": 0.005, "rsi_cool_threshold": 45},
        {"pullback_tolerance": 0.008, "rsi_cool_threshold": 55},
        {"pullback_tolerance": 0.015, "rsi_cool_threshold": 60},
        {"pullback_tolerance": 0.005, "rsi_cool_threshold": 55},
        {"pullback_tolerance": 0.01, "rsi_cool_threshold": 50},
    ]
    for i, combo in enumerate(best_combos):
        pt_str = str(combo["pullback_tolerance"]).replace(".", "")
        rct_str = str(combo["rsi_cool_threshold"])
        sets.append(ParamSet(
            label=f"combo{i}_pt{pt_str}_rct{rct_str}",
            scanner_params=combo,
            backtest_params={
                "signal_timeframe": "5m",
                "max_bars": 48,
                "target_r": 1.0,
                "skip_range": True,
                "max_pullback_quality": 0.7,
            },
        ))

    return sets


def run_backtest(param_set: ParamSet, symbols: list[str], direction: str,
                 start: str, end: str, production_root: str, db_name: str) -> dict[str, Any]:
    """Execute a single backtest run and return the parsed result."""
    cmd = [
        sys.executable, "-m", "scripts.run_backtest",
        "--scanner", "TREND_PULLBACK",
        "--direction", direction,
        "--from", start,
        "--to", end,
        "--symbols", *symbols,
        "--production-root", production_root,
        "--db-name", db_name,
    ]

    for key, value in param_set.scanner_params.items():
        arg_name = f"--{key.replace('_', '-')}"
        cmd.extend([arg_name, str(value)])

    for key, value in param_set.backtest_params.items():
        arg_name = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                cmd.append(arg_name)
        else:
            cmd.extend([arg_name, str(value)])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    output = result.stdout.strip()
    error = result.stderr.strip() if result.returncode != 0 else ""

    # Parse: run_id=<UUID> setups=<N> avg_r=<F> total_r=<F>
    run_id = None
    setups = 0
    avg_r = 0.0
    total_r = 0.0
    if result.returncode == 0 and "run_id=" in output:
        for part in output.split():
            if part.startswith("run_id="):
                run_id = part.split("=", 1)[1]
            elif part.startswith("setups="):
                setups = int(part.split("=", 1)[1])
            elif part.startswith("avg_r="):
                avg_r = float(part.split("=", 1)[1])
            elif part.startswith("total_r="):
                total_r = float(part.split("=", 1)[1])

    return {
        "label": param_set.label,
        "run_id": run_id,
        "setups": setups,
        "avg_r": avg_r,
        "total_r": total_r,
        "returncode": result.returncode,
        "output": output,
        "error": error,
        "scanner_params": json.dumps(param_set.scanner_params),
        "backtest_params": json.dumps(param_set.backtest_params),
    }


def fetch_detailed_metrics(connection, run_id: str) -> dict[str, Any]:
    """Fetch detailed metrics from bt tables for a given run."""
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT
                COUNT(*) as total_setups,
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) as entries,
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END) as tps,
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END) as sls,
                SUM(CASE WHEN o.first_event LIKE 'EXPIRED%' THEN 1 ELSE 0 END) as expired,
                SUM(CASE WHEN o.first_event = 'NO_ENTRY' THEN 1 ELSE 0 END) as no_entry,
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) as avg_r_entry,
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4) as total_r_entries,
                ROUND(AVG(o.result_r)::numeric, 4) as avg_r_all,
                ROUND(SUM(o.result_r)::numeric, 4) as total_r_all,
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.mfe_r END)::numeric, 4) as avg_mfe,
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.mae_r END)::numeric, 4) as avg_mae,
                ROUND(AVG(o.fee_slippage_adjusted_result_r)::numeric, 4) as avg_adjusted_r
            FROM bt.run r
            JOIN bt.setup s ON s.run_id = r.id
            JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s
        """, (run_id,))
        row = cursor.fetchone()
        if row:
            return {
                "total_setups": row[0] or 0,
                "entries": row[1] or 0,
                "tps": row[2] or 0,
                "sls": row[3] or 0,
                "expired": row[4] or 0,
                "no_entry": row[5] or 0,
                "avg_r_entry": float(row[6]) if row[6] else 0.0,
                "total_r_entries": float(row[7]) if row[7] else 0.0,
                "avg_r_all": float(row[8]) if row[8] else 0.0,
                "total_r_all": float(row[9]) if row[9] else 0.0,
                "avg_mfe": float(row[10]) if row[10] else 0.0,
                "avg_mae": float(row[11]) if row[11] else 0.0,
                "avg_adjusted_r": float(row[12]) if row[12] else 0.0,
            }
        return {}
    finally:
        cursor.close()


def fetch_regime_breakdown(connection, run_id: str) -> list[dict[str, Any]]:
    """Fetch breakdown by market regime."""
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT
                s.regime,
                COUNT(*) as setups,
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) as entries,
                SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END) as wins,
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) as avg_r,
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4) as total_r
            FROM bt.run r
            JOIN bt.setup s ON s.run_id = r.id
            JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s
            GROUP BY s.regime
            ORDER BY total_r DESC
        """, (run_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Grid search for TREND_PULLBACK optimization")
    parser.add_argument("--symbols", nargs="+", default=[
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT", "BNBUSDT",
        "XRPUSDT", "SUIUSDT", "ONDOUSDT", "NEARUSDT", "HYPEUSDT",
    ])
    parser.add_argument("--direction", default="LONG", choices=("LONG", "SHORT"))
    parser.add_argument("--from", dest="start", default="2025-01-01")
    parser.add_argument("--to", dest="end", default="2025-06-30")
    parser.add_argument("--production-root", default="../trad_bot")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--labels", nargs="*", help="Run only specific param set labels")
    parser.add_argument("--output", default="exports/grid_search_results.csv")
    args = parser.parse_args()

    param_sets = build_param_sets()
    if args.labels:
        param_sets = [ps for ps in param_sets if ps.label in args.labels]

    print(f"Grid search: {len(param_sets)} configurations × {len(args.symbols)} symbols")
    print(f"Direction: {args.direction}, Period: {args.start} to {args.end}")
    print(f"Total backtest runs: {len(param_sets)}")
    print()

    results = []
    connection = dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database=args.db_name,
    )

    try:
        for i, ps in enumerate(param_sets, 1):
            print(f"[{i}/{len(param_sets)}] Running: {ps.label} ...", end=" ", flush=True)
            raw = run_backtest(ps, args.symbols, args.direction, args.start, args.end,
                               args.production_root, args.db_name)
            if raw["run_id"]:
                metrics = fetch_detailed_metrics(connection, raw["run_id"])
                regimes = fetch_regime_breakdown(connection, raw["run_id"])
                raw["metrics"] = metrics
                raw["regimes"] = regimes
            results.append(raw)
            status = "OK" if raw["returncode"] == 0 else f"FAIL({raw['returncode']})"
            print(f"{status} setups={raw['setups']} avg_r={raw['avg_r']:.4f} total_r={raw['total_r']:.4f}")
    finally:
        connection.close()

    # Write results CSV
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "label", "run_id", "setups", "total_setups", "entries", "tps", "sls",
        "expired", "no_entry", "avg_r_entry", "total_r_entries", "avg_r_all",
        "total_r_all", "avg_mfe", "avg_mae", "avg_adjusted_r",
        "scanner_params", "backtest_params", "returncode",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            m = r.get("metrics", {})
            writer.writerow({
                "label": r["label"],
                "run_id": r["run_id"],
                "setups": r["setups"],
                "total_setups": m.get("total_setups", ""),
                "entries": m.get("entries", ""),
                "tps": m.get("tps", ""),
                "sls": m.get("sls", ""),
                "expired": m.get("expired", ""),
                "no_entry": m.get("no_entry", ""),
                "avg_r_entry": m.get("avg_r_entry", ""),
                "total_r_entries": m.get("total_r_entries", ""),
                "avg_r_all": m.get("avg_r_all", ""),
                "total_r_all": m.get("total_r_all", ""),
                "avg_mfe": m.get("avg_mfe", ""),
                "avg_mae": m.get("avg_mae", ""),
                "avg_adjusted_r": m.get("avg_adjusted_r", ""),
                "scanner_params": r.get("scanner_params", ""),
                "backtest_params": r.get("backtest_params", ""),
                "returncode": r["returncode"],
            })

    print(f"\nResults written to {output_path}")
    print(f"Total runs: {len(results)}, Successful: {sum(1 for r in results if r['returncode'] == 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
