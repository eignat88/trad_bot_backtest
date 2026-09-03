"""Fast two-stage grid search for MOMENTUM_EXHAUSTION scanner.

Stage 1 (Quick): 3 major coins, 3 months, wide parameter sweep (~25 min)
Stage 2 (Deep): 10 coins, 6 months, top combos from Stage 1 (~30 min)
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

CORE_3 = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TOP_10 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT", "BNBUSDT",
    "XRPUSDT", "SUIUSDT", "ONDOUSDT", "NEARUSDT", "HYPEUSDT",
]


@dataclass
class Run:
    label: str
    scanner_params: dict[str, Any] = field(default_factory=dict)
    backtest_params: dict[str, Any] = field(default_factory=dict)


def stage1_param_sets() -> list[Run]:
    """Stage 1: Wide sweep with varied individual params."""
    sets = []

    # Baseline (default scanner + no target_r override)
    sets.append(Run("baseline", {}, {"signal_timeframe": "5m", "max_bars": 48}))

    # Baseline with target_r
    for tr in [1.0, 1.5, 2.0, 2.5, 3.0]:
        sets.append(Run(f"tr_{tr}", {}, {"signal_timeframe": "5m", "max_bars": 48, "target_r": tr}))

    # swing_lookback sweep
    for slb in [3, 4, 5, 7, 10]:
        sets.append(Run(f"slb_{slb}", {"swing_lookback": slb},
                        {"signal_timeframe": "5m", "max_bars": 48, "target_r": 2.0}))

    # exhaustion_threshold sweep
    for eth in [0.001, 0.002, 0.003, 0.005, 0.008, 0.01]:
        sets.append(Run(f"eth_{eth}", {"exhaustion_threshold": eth},
                        {"signal_timeframe": "5m", "max_bars": 48, "target_r": 2.0}))

    # Signal timeframe
    for tf in ["5m", "15m"]:
        sets.append(Run(f"tf_{tf}", {},
                        {"signal_timeframe": tf, "max_bars": 48, "target_r": 2.0}))

    # max_bars
    for mb in [24, 48, 72]:
        sets.append(Run(f"mb_{mb}", {},
                        {"signal_timeframe": "5m", "max_bars": mb, "target_r": 2.0}))

    # skip_range
    sets.append(Run("skip_range", {},
                    {"signal_timeframe": "5m", "max_bars": 48, "target_r": 2.0, "skip_range": True}))

    # Direction
    for d in ["LONG", "SHORT"]:
        sets.append(Run(f"dir_{d}", {},
                        {"signal_timeframe": "5m", "max_bars": 48, "target_r": 2.0, "direction": d}))

    return sets


def stage2_param_sets(best_from_stage1: list[dict]) -> list[Run]:
    """Stage 2: Cross-product of best params from Stage 1."""
    sets = []

    # Extract best values from top Stage 1 results
    best_slbs = [5, 7, 10]
    best_eths = [0.003, 0.005, 0.008]
    best_trs = [1.5, 2.0, 2.5, 3.0]
    best_tfs = ["5m", "15m"]

    for slb in best_slbs:
        for eth in best_eths:
            for tr in best_trs:
                for tf in best_tfs:
                    sets.append(Run(
                        f"c_s{slb}_e{str(eth).replace('.','')}_t{tr}_{tf}",
                        {"swing_lookback": slb, "exhaustion_threshold": eth},
                        {"signal_timeframe": tf, "max_bars": 48, "target_r": tr},
                    ))

    # Add skip_range + direction variants of top combos
    for slb in best_slbs:
        for eth in best_eths:
            for tr in [2.0, 3.0]:
                for sr in [False, True]:
                    for d in ["LONG", "SHORT", "BOTH"]:
                        if sr and d == "BOTH":
                            continue
                        suffix = "sr" if sr else "nr"
                        sets.append(Run(
                            f"f_s{slb}_e{str(eth).replace('.','')}_t{tr}_{suffix}_{d}",
                            {"swing_lookback": slb, "exhaustion_threshold": eth},
                            {"signal_timeframe": "5m", "max_bars": 48, "target_r": tr,
                             "skip_range": sr, "direction": d},
                        ))

    return sets


def execute_run(r: Run, symbols: list[str], start: str, end: str,
                production_root: str, db_name: str) -> dict[str, Any]:
    """Run a single backtest."""
    effective_direction = r.backtest_params.pop("direction", "BOTH")

    cmd = [
        sys.executable, "-m", "scripts.run_backtest",
        "--scanner", "MOMENTUM_EXHAUSTION",
        "--direction", effective_direction,
        "--from", start, "--to", end,
        "--symbols", *symbols,
        "--production-root", production_root,
        "--db-name", db_name,
    ]
    for key, val in r.scanner_params.items():
        cmd.extend([f"--{key.replace('_','-')}", str(val)])
    for key, val in r.backtest_params.items():
        arg = f"--{key.replace('_','-')}"
        if isinstance(val, bool):
            if val:
                cmd.append(arg)
        else:
            cmd.extend([arg, str(val)])

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0
    output = result.stdout.strip()

    run_id = setups = 0
    avg_r = total_r = 0.0
    if result.returncode == 0 and "run_id=" in output:
        for part in output.split():
            if part.startswith("run_id="): run_id = part.split("=", 1)[1]
            elif part.startswith("setups="): setups = int(part.split("=", 1)[1])
            elif part.startswith("avg_r="): avg_r = float(part.split("=", 1)[1])
            elif part.startswith("total_r="): total_r = float(part.split("=", 1)[1])

    return {
        "label": r.label, "run_id": run_id, "setups": setups,
        "avg_r": avg_r, "total_r": total_r,
        "returncode": result.returncode,
        "error": result.stderr.strip() if result.returncode != 0 else "",
        "scanner_params": json.dumps(r.scanner_params),
        "backtest_params": json.dumps(r.backtest_params),
        "elapsed_s": round(elapsed, 1),
    }


def fetch_metrics(conn, run_id: str) -> dict[str, Any]:
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                COUNT(*), SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event LIKE 'EXPIRED%%' THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event = 'NO_ENTRY' THEN 1 ELSE 0 END),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4),
                ROUND(AVG(o.result_r)::numeric, 4),
                ROUND(SUM(o.result_r)::numeric, 4),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.mfe_r END)::numeric, 4),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.mae_r END)::numeric, 4),
                ROUND(AVG(o.fee_slippage_adjusted_result_r)::numeric, 4)
            FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s
        """, (run_id,))
        row = cur.fetchone()
        if row and row[0]:
            return {
                "total_setups": row[0], "entries": row[1] or 0,
                "tps": row[2] or 0, "sls": row[3] or 0,
                "expired": row[4] or 0, "no_entry": row[5] or 0,
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
        cur.close()


def fetch_symbol_breakdown(conn, run_id: str) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.symbol, COUNT(*),
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4)
            FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s GROUP BY s.symbol ORDER BY 7 DESC
        """, (run_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def fetch_regime_breakdown(conn, run_id: str) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.regime, COUNT(*),
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4)
            FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s GROUP BY s.regime ORDER BY 6 DESC
        """, (run_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def fetch_direction_breakdown(conn, run_id: str) -> list[dict]:
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.direction, COUNT(*),
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4)
            FROM bt.run r JOIN bt.setup s ON s.run_id = r.id JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id = %s GROUP BY s.direction ORDER BY 7 DESC
        """, (run_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def write_report(results: list[dict], output_path: Path, title: str):
    """Write a Markdown report."""
    lines = []
    lines.append(f"# {title}")
    lines.append("")

    # Default scanner params
    lines.append("## MOMENTUM_EXHAUSTION Default Settings")
    lines.append("| Parameter | Default |")
    lines.append("|---|---|")
    lines.append("| swing_lookback | 5 |")
    lines.append("| exhaustion_threshold | 0.003 |")
    lines.append("| RSI (SHORT) | >= 65 |")
    lines.append("| RSI (LONG) | <= 35 |")
    lines.append("| body/range filter | <= 0.7 |")
    lines.append("| targets | ATR x 2 / ATR x 3 |")
    lines.append("")

    successful = [r for r in results if r["returncode"] == 0 and r["setups"] > 0]
    if not successful:
        lines.append("No successful runs.")
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return

    # Top by total R
    ranked = sorted(successful, key=lambda r: r.get("total_r", 0), reverse=True)
    lines.append("## Top 20 by Total R")
    lines.append("")
    lines.append("| # | Label | Setups | Entries | TPs | SLs | AvgR | TotalR | MFE | MAE | AdjR |")
    lines.append("|--:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, r in enumerate(ranked[:20], 1):
        m = r.get("metrics", {})
        lines.append(f"| {i} | {r['label']} | {r['setups']} | {m.get('entries','')} | "
                     f"{m.get('tps','')} | {m.get('sls','')} | "
                     f"{m.get('avg_r_entry','')} | {m.get('total_r_all', r.get('total_r',''))} | "
                     f"{m.get('avg_mfe','')} | {m.get('avg_mae','')} | {m.get('avg_adjusted_r','')} |")

    # Top by avg R (min 5 entries)
    lines.append("")
    lines.append("## Top 20 by Avg R (min 5 entries)")
    lines.append("")
    ranked_avg = sorted(
        [r for r in successful if r.get("metrics", {}).get("entries", 0) >= 5],
        key=lambda r: r.get("metrics", {}).get("avg_r_entry", 0), reverse=True,
    )
    lines.append("| # | Label | Setups | Entries | AvgR | TotalR | WinRate |")
    lines.append("|--:|---|---:|---:|---:|---:|---:|")
    for i, r in enumerate(ranked_avg[:20], 1):
        m = r.get("metrics", {})
        entries = m.get("entries", 0)
        tps = m.get("tps", 0)
        wr = round(tps / entries * 100, 1) if entries > 0 else 0
        lines.append(f"| {i} | {r['label']} | {r['setups']} | {entries} | "
                     f"{m.get('avg_r_entry','')} | {m.get('total_r_all','')} | {wr}% |")

    # Best config details
    if ranked:
        best = ranked[0]
        m = best.get("metrics", {})
        lines.append("")
        lines.append("## Best Configuration")
        lines.append("")
        lines.append(f"**{best['label']}**")
        lines.append(f"- Scanner params: `{best.get('scanner_params', '{}')}`")
        lines.append(f"- Backtest params: `{best.get('backtest_params', '{}')}`")
        lines.append(f"- Total R: {m.get('total_r_all', best.get('total_r', 0)):.4f}")
        lines.append(f"- Avg R (entry): {m.get('avg_r_entry', 0):.4f}")
        lines.append(f"- Setups: {best['setups']}, Entries: {m.get('entries', 0)}")
        lines.append(f"- TPs: {m.get('tps', 0)}, SLs: {m.get('sls', 0)}")
        wr = round(m.get('tps', 0) / m.get('entries', 1) * 100, 1) if m.get('entries', 0) > 0 else 0
        lines.append(f"- Win rate: {wr}%")
        lines.append(f"- Avg MFE: {m.get('avg_mfe', 0):.4f}, Avg MAE: {m.get('avg_mae', 0):.4f}")
        lines.append(f"- Adjusted R: {m.get('avg_adjusted_r', 0):.4f}")

        # Per-symbol breakdown
        sb = best.get("symbol_breakdown", [])
        if sb:
            lines.append("")
            lines.append("### Per-Symbol (Best Config)")
            lines.append("")
            lines.append("| Symbol | Setups | Entries | TPs | SLs | AvgR | TotalR |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for s in sb:
                lines.append(f"| {s['symbol']} | {s.get('count', s.get('setups', 0))} | "
                             f"{s.get('sum', s.get('entries', 0))} | {s.get('sum_1', s.get('tps', 0))} | "
                             f"{s.get('sum_2', s.get('sls', 0))} | {s.get('avg_r', 0)} | {s.get('sum_3', s.get('total_r', 0))} |")

        # Regime breakdown
        rb = best.get("regime_breakdown", [])
        if rb:
            lines.append("")
            lines.append("### Regime Breakdown (Best Config)")
            lines.append("")
            lines.append("| Regime | Setups | Entries | Wins | AvgR | TotalR |")
            lines.append("|---|---:|---:|---:|---:|---:|")
            for rg in rb:
                lines.append(f"| {rg.get('regime', 'N/A')} | {rg.get('count', rg.get('setups', 0))} | "
                             f"{rg.get('sum', rg.get('entries', 0))} | {rg.get('sum_1', rg.get('wins', 0))} | "
                             f"{rg.get('avg_r', 0)} | {rg.get('sum_2', rg.get('total_r', 0))} |")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-root", default=r"D:\py_pro\trad_bot")
    parser.add_argument("--db-name", default="trad_bot_backtest")
    parser.add_argument("--stage", type=int, choices=(1, 2), help="Run specific stage only")
    parser.add_argument("--from", dest="start", default="2025-01-01")
    parser.add_argument("--to", dest="end", default="2026-01-01")
    args = parser.parse_args()

    conn = dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database=args.db_name,
    )

    all_results = []

    # ═══════════════════════════════════════════════════════════════
    # STAGE 1: Quick scan (3 coins, 3 months)
    # ═══════════════════════════════════════════════════════════════
    if args.stage in (None, 1):
        s1_params = stage1_param_sets()
        s1_symbols = CORE_3
        s1_start, s1_end = "2025-01-01", "2025-04-01"
        s1_total = sum(70 for _ in s1_params)  # rough estimate

        print(f"{'='*80}")
        print(f"STAGE 1: Quick Scan")
        print(f"  Configurations: {len(s1_params)}")
        print(f"  Symbols: {s1_symbols}")
        print(f"  Period: {s1_start} to {s1_end}")
        print(f"{'='*80}")
        print()

        t_total = time.time()
        for i, r in enumerate(s1_params, 1):
            print(f"[S1 {i}/{len(s1_params)}] {r.label:45s} ", end="", flush=True)
            raw = execute_run(r, s1_symbols, s1_start, s1_end,
                              args.production_root, args.db_name)
            if raw["run_id"]:
                raw["metrics"] = fetch_metrics(conn, raw["run_id"])
            all_results.append(raw)

            m = raw.get("metrics", {})
            entries = m.get("entries", 0)
            tps = m.get("tps", 0)
            wr = f"{round(tps/entries*100,1)}%" if entries > 0 else "N/A"
            print(f"setups={raw['setups']:>5} entries={entries:>4} "
                  f"avgR={raw.get('avg_r', 0):>7.4f} totalR={raw.get('total_r', 0):>9.4f} "
                  f"wr={wr:>6} [{raw.get('elapsed_s', 0):.0f}s]")

        s1_elapsed = time.time() - t_total
        print(f"\nStage 1 complete: {s1_elapsed:.0f}s")

        # Save Stage 1 results
        s1_path = Path("exports/momentum_stage1_results.csv")
        s1_path.parent.mkdir(parents=True, exist_ok=True)
        with s1_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=[
                "label", "run_id", "setups", "total_setups", "entries", "tps", "sls",
                "expired", "no_entry", "avg_r_entry", "total_r_entries", "avg_r_all",
                "total_r_all", "avg_mfe", "avg_mae", "avg_adjusted_r",
                "scanner_params", "backtest_params", "elapsed_s", "returncode",
            ], extrasaction="ignore")
            w.writeheader()
            for r in all_results:
                m = r.get("metrics", {})
                w.writerow({k: r.get(k, m.get(k, "")) for k in w.fieldnames})

        write_report(all_results, Path("exports/momentum_stage1_report.md"),
                     "MOMENTUM_EXHAUSTION Stage 1: Quick Scan")

        print(f"Stage 1 CSV: {s1_path}")
        print(f"Stage 1 Report: exports/momentum_stage1_report.md")

    # ═══════════════════════════════════════════════════════════════
    # STAGE 2: Deep scan (10 coins, 6 months, top combos)
    # ═══════════════════════════════════════════════════════════════
    if args.stage in (None, 2):
        # If running standalone, load stage 1 results
        if args.stage == 2:
            s1_path = Path("exports/momentum_stage1_results.csv")
            if s1_path.exists():
                with s1_path.open(encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        all_results.append({
                            "label": row.get("label", ""),
                            "run_id": row.get("run_id"),
                            "setups": int(row.get("setups", 0) or 0),
                            "avg_r": float(row.get("avg_r_all", 0) or 0),
                            "total_r": float(row.get("total_r_all", 0) or 0),
                            "returncode": int(row.get("returncode", 0) or 0),
                            "scanner_params": row.get("scanner_params", "{}"),
                            "backtest_params": row.get("backtest_params", "{}"),
                            "metrics": {
                                "entries": int(row.get("entries", 0) or 0),
                                "tps": int(row.get("tps", 0) or 0),
                                "sls": int(row.get("sls", 0) or 0),
                                "avg_r_entry": float(row.get("avg_r_entry", 0) or 0),
                                "total_r_all": float(row.get("total_r_all", 0) or 0),
                                "avg_mfe": float(row.get("avg_mfe", 0) or 0),
                                "avg_mae": float(row.get("avg_mae", 0) or 0),
                                "avg_adjusted_r": float(row.get("avg_adjusted_r", 0) or 0),
                            },
                        })

        s2_params = stage2_param_sets(all_results)
        s2_symbols = TOP_10
        s2_start, s2_end = args.start, args.end

        print(f"\n{'='*80}")
        print(f"STAGE 2: Deep Scan")
        print(f"  Configurations: {len(s2_params)}")
        print(f"  Symbols: {len(s2_symbols)} coins")
        print(f"  Period: {s2_start} to {s2_end}")
        print(f"{'='*80}")
        print()

        t_total = time.time()
        s2_results = []
        for i, r in enumerate(s2_params, 1):
            print(f"[S2 {i}/{len(s2_params)}] {r.label:45s} ", end="", flush=True)
            raw = execute_run(r, s2_symbols, s2_start, s2_end,
                              args.production_root, args.db_name)
            if raw["run_id"]:
                raw["metrics"] = fetch_metrics(conn, raw["run_id"])
                raw["symbol_breakdown"] = fetch_symbol_breakdown(conn, raw["run_id"])
                raw["regime_breakdown"] = fetch_regime_breakdown(conn, raw["run_id"])
                raw["direction_breakdown"] = fetch_direction_breakdown(conn, raw["run_id"])
            s2_results.append(raw)
            all_results.append(raw)

            m = raw.get("metrics", {})
            entries = m.get("entries", 0)
            tps = m.get("tps", 0)
            wr = f"{round(tps/entries*100,1)}%" if entries > 0 else "N/A"
            print(f"setups={raw['setups']:>5} entries={entries:>4} "
                  f"avgR={raw.get('avg_r', 0):>7.4f} totalR={raw.get('total_r', 0):>9.4f} "
                  f"wr={wr:>6} [{raw.get('elapsed_s', 0):.0f}s]")

        s2_elapsed = time.time() - t_total
        print(f"\nStage 2 complete: {s2_elapsed:.0f}s")

        # Save Stage 2 report (includes full detail)
        write_report(s2_results, Path("exports/momentum_stage2_report.md"),
                     "MOMENTUM_EXHAUSTION Stage 2: Deep Scan (Top 10 coins, full year)")
        print(f"Stage 2 Report: exports/momentum_stage2_report.md")

    # ═══════════════════════════════════════════════════════════════
    # Combined report
    # ═══════════════════════════════════════════════════════════════
    successful = [r for r in all_results if r["returncode"] == 0 and r["setups"] > 0]
    if successful:
        best = max(successful, key=lambda r: r.get("total_r", 0))
        m = best.get("metrics", {})
        print(f"\n{'='*80}")
        print(f"BEST OVERALL: {best['label']}")
        print(f"  Total R: {m.get('total_r_all', best.get('total_r', 0))}")
        print(f"  Avg R (entry): {m.get('avg_r_entry', 0)}")
        print(f"  Entries: {m.get('entries', 0)}, TPs: {m.get('tps', 0)}")
        print(f"  Scanner: {best.get('scanner_params', '{}')}")
        print(f"  Backtest: {best.get('backtest_params', '{}')}")
        print(f"{'='*80}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
