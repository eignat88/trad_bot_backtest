"""Grid search optimization for MOMENTUM_EXHAUSTION scanner.

Runs multiple backtest configurations across top-10 crypto pairs,
collecting results to identify the most profitable parameter combinations.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
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

    # ═══════════════════════════════════════════════════════════════════
    # Phase 1: BASELINE (production defaults)
    # ═══════════════════════════════════════════════════════════════════
    sets.append(ParamSet(
        label="baseline",
        scanner_params={},
        backtest_params={"signal_timeframe": "5m", "max_bars": 48, "target_r": 1.5},
    ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2: swing_lookback sweep (controls swing detection sensitivity)
    # Lower = more swings detected = more setups
    # ═══════════════════════════════════════════════════════════════════
    for slb in [3, 4, 5, 6, 8, 10, 12]:
        sets.append(ParamSet(
            label=f"slb_{slb}",
            scanner_params={"swing_lookback": slb},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48, "target_r": 1.5},
        ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 3: exhaustion_threshold sweep (how far past swing to trigger)
    # Smaller = more sensitive = more setups, but potentially noisier
    # ═══════════════════════════════════════════════════════════════════
    for eth in [0.001, 0.002, 0.003, 0.005, 0.007, 0.01, 0.015, 0.02]:
        sets.append(ParamSet(
            label=f"eth_{eth}",
            scanner_params={"exhaustion_threshold": eth},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48, "target_r": 1.5},
        ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 4: signal_timeframe sweep (5m vs 15m candle resolution)
    # ═══════════════════════════════════════════════════════════════════
    for tf in ["5m", "15m"]:
        sets.append(ParamSet(
            label=f"tf_{tf}",
            scanner_params={},
            backtest_params={"signal_timeframe": tf, "max_bars": 48, "target_r": 1.5},
        ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 5: target_r sweep (take profit in R multiples)
    # ═══════════════════════════════════════════════════════════════════
    for tr in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        sets.append(ParamSet(
            label=f"tr_{tr}",
            scanner_params={},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48, "target_r": tr},
        ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 6: max_bars sweep (evaluation window after signal)
    # ═══════════════════════════════════════════════════════════════════
    for mb in [12, 24, 36, 48, 72, 96]:
        sets.append(ParamSet(
            label=f"mb_{mb}",
            scanner_params={},
            backtest_params={"signal_timeframe": "5m", "max_bars": mb, "target_r": 1.5},
        ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 7: skip_range (filter out RANGE regime)
    # ═══════════════════════════════════════════════════════════════════
    sets.append(ParamSet(
        label="skip_range_true",
        scanner_params={},
        backtest_params={"signal_timeframe": "5m", "max_bars": 48, "target_r": 1.5, "skip_range": True},
    ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 8: Direction comparison
    # ═══════════════════════════════════════════════════════════════════
    for d in ["LONG", "SHORT", "BOTH"]:
        sets.append(ParamSet(
            label=f"dir_{d}",
            scanner_params={},
            backtest_params={"signal_timeframe": "5m", "max_bars": 48, "target_r": 1.5, "direction": d},
        ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 9: COMBINED BEST — cross product of promising params
    # ═══════════════════════════════════════════════════════════════════
    best_swing_lookbacks = [4, 5, 6, 8]
    best_thresholds = [0.002, 0.003, 0.005]
    best_targets = [1.0, 1.5, 2.0]
    best_timeframes = ["5m", "15m"]

    for slb in best_swing_lookbacks:
        for eth in best_thresholds:
            for tr in best_targets:
                for tf in best_timeframes:
                    sets.append(ParamSet(
                        label=f"combo_slb{slb}_eth{str(eth).replace('.','')}_tr{tr}_tf{tf}",
                        scanner_params={"swing_lookback": slb, "exhaustion_threshold": eth},
                        backtest_params={"signal_timeframe": tf, "max_bars": 48, "target_r": tr},
                    ))

    # ═══════════════════════════════════════════════════════════════════
    # Phase 10: COMBINED with skip_range + direction variants
    # ═══════════════════════════════════════════════════════════════════
    for slb in [5, 8]:
        for eth in [0.003, 0.005]:
            for tr in [1.5, 2.0]:
                for sr in [False, True]:
                    for d in ["LONG", "SHORT", "BOTH"]:
                        sets.append(ParamSet(
                            label=f"full_slb{slb}_eth{str(eth).replace('.','')}_tr{tr}_{'sr' if sr else 'nr'}_{d}",
                            scanner_params={"swing_lookback": slb, "exhaustion_threshold": eth},
                            backtest_params={
                                "signal_timeframe": "5m",
                                "max_bars": 48,
                                "target_r": tr,
                                "skip_range": sr,
                                "direction": d,
                            },
                        ))

    return sets


TOP_10_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT", "BNBUSDT",
    "XRPUSDT", "SUIUSDT", "ONDOUSDT", "NEARUSDT", "HYPEUSDT",
]


def run_backtest(param_set: ParamSet, symbols: list[str], direction: str,
                 start: str, end: str, production_root: str, db_name: str) -> dict[str, Any]:
    """Execute a single backtest run and return the parsed result."""
    # Use param_set direction if overridden
    effective_direction = param_set.backtest_params.pop("direction", direction)

    cmd = [
        sys.executable, "-m", "scripts.run_backtest",
        "--scanner", "MOMENTUM_EXHAUSTION",
        "--direction", effective_direction,
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

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    elapsed = time.time() - t0
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
        "elapsed_s": round(elapsed, 1),
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
                SUM(CASE WHEN o.first_event LIKE 'EXPIRED%%' THEN 1 ELSE 0 END) as expired,
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


def fetch_symbol_breakdown(connection, run_id: str) -> list[dict[str, Any]]:
    """Fetch per-symbol breakdown for a given run."""
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT
                s.symbol,
                COUNT(*) as setups,
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) as entries,
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END) as tps,
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END) as sls,
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) as avg_r,
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4) as total_r
            FROM bt.run r
            JOIN bt.setup s ON s.run_id = r.id
            JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s
            GROUP BY s.symbol ORDER BY total_r DESC
        """, (run_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
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


def fetch_direction_breakdown(connection, run_id: str) -> list[dict[str, Any]]:
    """Fetch breakdown by direction (LONG/SHORT)."""
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT
                s.direction,
                COUNT(*) as setups,
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) as entries,
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END) as tps,
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END) as sls,
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4) as avg_r,
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4) as total_r
            FROM bt.run r
            JOIN bt.setup s ON s.run_id = r.id
            JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s
            GROUP BY s.direction ORDER BY total_r DESC
        """, (run_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def generate_report(results: list[dict[str, Any]], phases: dict[str, int]) -> str:
    """Generate a human-readable optimization report."""
    lines = []
    lines.append("# MOMENTUM_EXHAUSTION Optimization Report")
    lines.append("")
    lines.append("## Scanner Defaults")
    lines.append("| Parameter | Default |")
    lines.append("|---|---|")
    lines.append("| swing_lookback | 5 |")
    lines.append("| exhaustion_threshold | 0.003 |")
    lines.append("| RSI threshold (SHORT) | ≥ 65 |")
    lines.append("| RSI threshold (LONG) | ≤ 35 |")
    lines.append("| Body/range filter | ≤ 0.7 |")
    lines.append("| Targets | ATR × 2 / ATR × 3 |")
    lines.append("")

    # ── Top 10 by total_r ──
    successful = [r for r in results if r["returncode"] == 0 and r["setups"] > 0]
    if not successful:
        lines.append("No successful runs.")
        return "\n".join(lines)

    ranked = sorted(successful, key=lambda r: r.get("total_r", 0), reverse=True)

    lines.append("## Top 15 Configurations by Total R")
    lines.append("")
    lines.append("| Rank | Label | Setups | Entries | TPs | SLs | AvgR(entry) | TotalR | Avg MFE | Avg MAE | Adj R |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, r in enumerate(ranked[:15], 1):
        m = r.get("metrics", {})
        lines.append(
            f"| {i} | {r['label']} | {r['setups']} | {m.get('entries','')} | "
            f"{m.get('tps','')} | {m.get('sls','')} | "
            f"{m.get('avg_r_entry','')} | {m.get('total_r_all', r.get('total_r',''))} | "
            f"{m.get('avg_mfe','')} | {m.get('avg_mae','')} | {m.get('avg_adjusted_r','')} |"
        )

    lines.append("")
    lines.append("## Top 15 by Avg R (Entry)")
    lines.append("")
    ranked_avg = sorted(
        [r for r in successful if r.get("metrics", {}).get("entries", 0) >= 5],
        key=lambda r: r.get("metrics", {}).get("avg_r_entry", 0),
        reverse=True,
    )
    lines.append("| Rank | Label | Setups | Entries | AvgR(entry) | TotalR | WinRate |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|")
    for i, r in enumerate(ranked_avg[:15], 1):
        m = r.get("metrics", {})
        entries = m.get("entries", 0)
        tps = m.get("tps", 0)
        winrate = round(tps / entries * 100, 1) if entries > 0 else 0
        lines.append(
            f"| {i} | {r['label']} | {r['setups']} | {entries} | "
            f"{m.get('avg_r_entry','')} | {m.get('total_r_all','')} | {winrate}% |"
        )

    # ── Phase summaries ──
    lines.append("")
    lines.append("## Phase Summaries")
    lines.append("")
    phase_idx = 0
    for phase_name, count in phases.items():
        phase_results = results[phase_idx:phase_idx + count]
        phase_idx += count
        phase_successful = [r for r in phase_results if r["returncode"] == 0]
        if not phase_successful:
            continue
        best = max(phase_successful, key=lambda r: r.get("total_r", 0))
        m = best.get("metrics", {})
        lines.append(f"### {phase_name}")
        lines.append(f"- Configs tested: {count}")
        lines.append(f"- Best: **{best['label']}** => Total R = {best.get('total_r', 0):.2f}, "
                      f"Avg R(entry) = {m.get('avg_r_entry', 0):.4f}, "
                      f"Setups = {best['setups']}, Entries = {m.get('entries', 0)}")
        lines.append("")

    # ── Best config details ──
    if ranked:
        best = ranked[0]
        lines.append("## Recommended Configuration")
        lines.append("")
        lines.append(f"**{best['label']}**")
        lines.append(f"- Scanner params: `{best.get('scanner_params', '{}')}`")
        lines.append(f"- Backtest params: `{best.get('backtest_params', '{}')}`")
        lines.append(f"- Total R: {best.get('total_r', 0):.4f}")  # noqa
        m = best.get("metrics", {})
        lines.append(f"- Avg R (entry): {m.get('avg_r_entry', 0):.4f}")
        lines.append(f"- Setups: {best['setups']}, Entries: {m.get('entries', 0)}")
        lines.append(f"- TPs: {m.get('tps', 0)}, SLs: {m.get('sls', 0)}")
        lines.append(f"- Avg MFE: {m.get('avg_mfe', 0):.4f}, Avg MAE: {m.get('avg_mae', 0):.4f}")
        lines.append(f"- Adjusted R: {m.get('avg_adjusted_r', 0):.4f}")
        lines.append("")

        # Per-symbol breakdown for the best run
        symbol_data = best.get("symbol_breakdown", [])
        if symbol_data:
            lines.append("### Per-Symbol Breakdown (Best Config)")
            lines.append("")
            lines.append("| Symbol | Setups | Entries | TPs | SLs | Avg R | Total R |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for s in symbol_data:
                lines.append(f"| {s['symbol']} | {s['setups']} | {s['entries']} | {s['tps']} | {s['sls']} | {s['avg_r'] or 0} | {s['total_r'] or 0} |")
            lines.append("")

        # Regime breakdown
        regime_data = best.get("regime_breakdown", [])
        if regime_data:
            lines.append("### Regime Breakdown (Best Config)")
            lines.append("")
            lines.append("| Regime | Setups | Entries | Wins | Avg R | Total R |")
            lines.append("|---|---:|---:|---:|---:|---:|")
            for rg in regime_data:
                lines.append(f"| {rg['regime'] or 'N/A'} | {rg['setups']} | {rg['entries']} | {rg['wins']} | {rg['avg_r'] or 0} | {rg['total_r'] or 0} |")
            lines.append("")

        # Direction breakdown
        dir_data = best.get("direction_breakdown", [])
        if dir_data:
            lines.append("### Direction Breakdown (Best Config)")
            lines.append("")
            lines.append("| Direction | Setups | Entries | TPs | SLs | Avg R | Total R |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for dd in dir_data:
                lines.append(f"| {dd['direction']} | {dd['setups']} | {dd['entries']} | {dd['tps']} | {dd['sls']} | {dd['avg_r'] or 0} | {dd['total_r'] or 0} |")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Grid search for MOMENTUM_EXHAUSTION optimization")
    parser.add_argument("--symbols", nargs="+", default=TOP_10_SYMBOLS)
    parser.add_argument("--direction", default="BOTH", choices=("LONG", "SHORT", "BOTH"))
    parser.add_argument("--from", dest="start", default="2025-01-01")
    parser.add_argument("--to", dest="end", default="2026-01-01")
    parser.add_argument("--production-root", default="../trad_bot")
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--labels", nargs="*", help="Run only specific param set labels (prefix match)")
    parser.add_argument("--phase", type=int, help="Run only a specific phase (1-based)")
    parser.add_argument("--output", default="exports/momentum_exhaustion_grid_results.csv")
    parser.add_argument("--report", default="exports/momentum_exhaustion_optimization_report.md")
    args = parser.parse_args()

    all_param_sets = build_param_sets()

    # Map phases: each phase starts at a specific index
    phase_boundaries = {}
    idx = 0
    phase_names = [
        "Phase 1: Baseline",
        "Phase 2: swing_lookback sweep",
        "Phase 3: exhaustion_threshold sweep",
        "Phase 4: signal_timeframe sweep",
        "Phase 5: target_r sweep",
        "Phase 6: max_bars sweep",
        "Phase 7: skip_range filter",
        "Phase 8: Direction comparison",
        "Phase 9: Combined best cross-product",
        "Phase 10: Full combined with skip_range + direction",
    ]
    phase_counts = [1, 7, 8, 2, 6, 6, 1, 3, 48, 72]
    for name, count in zip(phase_names, phase_counts):
        phase_boundaries[name] = (idx, idx + count)
        idx += count

    if args.phase:
        phase_key = phase_names[args.phase - 1]
        start_idx, end_idx = phase_boundaries[phase_key]
        param_sets = all_param_sets[start_idx:end_idx]
        print(f"Running {phase_key}: {len(param_sets)} configurations")
    elif args.labels:
        param_sets = [ps for ps in all_param_sets if any(ps.label.startswith(l) for l in args.labels)]
        if not param_sets:
            print("No matching param sets found for labels:", args.labels)
            return 1
    else:
        param_sets = all_param_sets

    print(f"MOMENTUM_EXHAUSTION Grid Search")
    print(f"  Configurations: {len(param_sets)}")
    print(f"  Symbols: {len(args.symbols)} ({', '.join(args.symbols[:5])}...)")
    print(f"  Direction: {args.direction}")
    print(f"  Period: {args.start} to {args.end}")
    print()

    results = []
    connection = dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database=args.db_name,
    )

    total_time = 0
    try:
        for i, ps in enumerate(param_sets, 1):
            print(f"[{i}/{len(param_sets)}] {ps.label:50s} ... ", end="", flush=True)
            raw = run_backtest(ps, args.symbols, args.direction, args.start, args.end,
                               args.production_root, args.db_name)
            total_time += raw.get("elapsed_s", 0)

            if raw["run_id"]:
                metrics = fetch_detailed_metrics(connection, raw["run_id"])
                regimes = fetch_regime_breakdown(connection, raw["run_id"])
                symbols = fetch_symbol_breakdown(connection, raw["run_id"])
                directions = fetch_direction_breakdown(connection, raw["run_id"])
                raw["metrics"] = metrics
                raw["regimes"] = regimes
                raw["symbol_breakdown"] = symbols
                raw["direction_breakdown"] = directions
            results.append(raw)

            status = "OK" if raw["returncode"] == 0 else f"FAIL({raw['returncode']})"
            m = raw.get("metrics", {})
            entries = m.get("entries", 0)
            tps = m.get("tps", 0)
            winrate = f"{round(tps/entries*100,1)}%" if entries > 0 else "N/A"
            print(f"{status} setups={raw['setups']:>4} entries={entries:>4} "
                  f"avg_r={raw.get('avg_r', 0):>7.4f} total_r={raw.get('total_r', 0):>10.4f} "
                  f"wr={winrate:>6} [{raw.get('elapsed_s', 0):.0f}s]")
    finally:
        connection.close()

    # ── Write CSV ──
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "label", "run_id", "setups", "total_setups", "entries", "tps", "sls",
        "expired", "no_entry", "avg_r_entry", "total_r_entries", "avg_r_all",
        "total_r_all", "avg_mfe", "avg_mae", "avg_adjusted_r",
        "scanner_params", "backtest_params", "elapsed_s", "returncode",
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
                "elapsed_s": r.get("elapsed_s", ""),
                "returncode": r["returncode"],
            })

    # ── Write Report ──
    phases_used = {}
    if not args.phase and not args.labels:
        idx = 0
        for name, count in zip(phase_names, phase_counts):
            phases_used[name] = count
            idx += count
    else:
        phases_used["Custom run"] = len(param_sets)

    report = generate_report(results, phases_used)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    # ── Summary ──
    successful = [r for r in results if r["returncode"] == 0 and r["setups"] > 0]
    print(f"\n{'='*80}")
    print(f"Total runs: {len(results)}, Successful: {len(successful)}, Total time: {total_time:.0f}s")
    print(f"CSV:   {output_path}")
    print(f"Report: {report_path}")
    if successful:
        best = max(successful, key=lambda r: r.get("total_r", 0))
        m = best.get("metrics", {})
        print(f"\nBEST: {best['label']}")
        print(f"  Total R: {best.get('total_r', 0):.4f}")
        print(f"  Avg R(entry): {m.get('avg_r_entry', 0):.4f}")
        print(f"  Setups: {best['setups']}, Entries: {m.get('entries', 0)}, TPs: {m.get('tps', 0)}")
        print(f"  Scanner params: {best.get('scanner_params', '{}')}")
        print(f"  Backtest params: {best.get('backtest_params', '{}')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
