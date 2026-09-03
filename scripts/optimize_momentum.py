"""Focused MOMENTUM_EXHAUSTION optimization - 30 key configurations."""
import os, subprocess, sys, time, json
from pg8000 import dbapi

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT", "BNBUSDT",
           "XRPUSDT", "SUIUSDT", "ONDOUSDT", "NEARUSDT", "HYPEUSDT"]

CONFIGS = [
    # (label, extra_cli_args)
    # --- Baseline variants ---
    ("base_no_tr", []),
    ("base_tr1", ["--target-r", "1.0"]),
    ("base_tr2", ["--target-r", "2.0"]),
    ("base_tr3", ["--target-r", "3.0"]),
    # --- Direction ---
    ("dir_long", ["--direction", "LONG", "--target-r", "2.0"]),
    ("dir_short", ["--direction", "SHORT", "--target-r", "2.0"]),
    # --- Timeframe ---
    ("tf15_tr2", ["--signal-timeframe", "15m", "--target-r", "2.0"]),
    ("tf15_tr3", ["--signal-timeframe", "15m", "--target-r", "3.0"]),
    # --- swing_lookback combos ---
    ("slb7_tr2", ["--swing-lookback", "7", "--target-r", "2.0"]),
    ("slb10_tr2", ["--swing-lookback", "10", "--target-r", "2.0"]),
    ("slb10_tr3", ["--swing-lookback", "10", "--target-r", "3.0"]),
    # --- exhaustion_threshold combos ---
    ("eth5_tr2", ["--exhaustion-threshold", "0.005", "--target-r", "2.0"]),
    ("eth8_tr2", ["--exhaustion-threshold", "0.008", "--target-r", "2.0"]),
    ("eth10_tr2", ["--exhaustion-threshold", "0.01", "--target-r", "2.0"]),
    # --- skip_range ---
    ("sr_tr2", ["--skip-range", "--target-r", "2.0"]),
    ("sr_tr3", ["--skip-range", "--target-r", "3.0"]),
    # --- Combined: slb high + eth high + tr ---
    ("s10_e5_tr2", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "2.0"]),
    ("s10_e5_tr3", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0"]),
    ("s10_e8_tr3", ["--swing-lookback", "10", "--exhaustion-threshold", "0.008", "--target-r", "3.0"]),
    ("s7_e5_tr2", ["--swing-lookback", "7", "--exhaustion-threshold", "0.005", "--target-r", "2.0"]),
    # --- Combined + skip_range ---
    ("s10_e5_tr2_sr", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "2.0", "--skip-range"]),
    ("s10_e5_tr3_sr", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0", "--skip-range"]),
    # --- Combined + 15m ---
    ("s10_e5_tr2_15m", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "2.0", "--signal-timeframe", "15m"]),
    ("s10_e5_tr3_15m", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0", "--signal-timeframe", "15m"]),
    # --- Direction filtered combos ---
    ("s10_e5_tr2_long", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "2.0", "--direction", "LONG"]),
    ("s10_e5_tr3_short", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0", "--direction", "SHORT"]),
    # --- max_bars variations ---
    ("s10_e5_tr3_mb72", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0", "--max-bars", "72"]),
    ("s10_e5_tr3_mb96", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0", "--max-bars", "96"]),
    # --- Very aggressive ---
    ("s10_e8_tr3_sr_15m", ["--swing-lookback", "10", "--exhaustion-threshold", "0.008", "--target-r", "3.0", "--skip-range", "--signal-timeframe", "15m"]),
    # --- Very conservative ---
    ("s10_e10_tr3_15m", ["--swing-lookback", "10", "--exhaustion-threshold", "0.01", "--target-r", "3.0", "--signal-timeframe", "15m"]),
]


def run_one(label, extra):
    cmd = [
        sys.executable, "-m", "scripts.run_backtest",
        "--scanner", "MOMENTUM_EXHAUSTION",
        "--direction", "BOTH",
        "--from", "2025-01-01", "--to", "2025-12-31",
        "--symbols", *SYMBOLS,
        "--production-root", r"D:\py_pro\trad_bot",
        "--db-name", "trad_bot_backtest",
    ] + extra
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - t0
    out = r.stdout.strip()
    run_id = setups = 0
    avg_r = total_r = 0.0
    if r.returncode == 0 and "run_id=" in out:
        for p in out.split():
            if p.startswith("run_id="): run_id = p.split("=", 1)[1]
            elif p.startswith("setups="): setups = int(p.split("=", 1)[1])
            elif p.startswith("avg_r="): avg_r = float(p.split("=", 1)[1])
            elif p.startswith("total_r="): total_r = float(p.split("=", 1)[1])
    return {
        "label": label, "run_id": run_id, "setups": setups,
        "avg_r": round(avg_r, 4), "total_r": round(total_r, 4),
        "elapsed": round(elapsed, 1),
        "cli_args": " ".join(extra) if extra else "(default)",
    }


def fetch_metrics(conn, run_id):
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COUNT(*),
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
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
            FROM bt.run r JOIN bt.setup s ON s.run_id=r.id JOIN bt.outcome o ON o.setup_id=s.id
            WHERE r.id = %s
        """, (run_id,))
        row = cur.fetchone()
        if row and row[0]:
            return {
                "total_setups": row[0], "entries": row[1] or 0, "tps": row[2] or 0,
                "sls": row[3] or 0, "expired": row[4] or 0, "no_entry": row[5] or 0,
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


def fetch_by_symbol(conn, run_id):
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.symbol, COUNT(*),
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4)
            FROM bt.run r JOIN bt.setup s ON s.run_id=r.id JOIN bt.outcome o ON o.setup_id=s.id
            WHERE r.id = %s GROUP BY s.symbol ORDER BY 7 DESC
        """, (run_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def fetch_by_regime(conn, run_id):
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.regime, COUNT(*),
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.result_r > 0 THEN 1 ELSE 0 END),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4)
            FROM bt.run r JOIN bt.setup s ON s.run_id=r.id JOIN bt.outcome o ON o.setup_id=s.id
            WHERE r.id = %s GROUP BY s.regime ORDER BY 6 DESC
        """, (run_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def fetch_by_direction(conn, run_id):
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT s.direction, COUNT(*),
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END),
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END),
                ROUND(AVG(CASE WHEN o.entry_touched THEN o.result_r END)::numeric, 4),
                ROUND(SUM(CASE WHEN o.entry_touched THEN o.result_r ELSE 0 END)::numeric, 4)
            FROM bt.run r JOIN bt.setup s ON s.run_id=r.id JOIN bt.outcome o ON o.setup_id=s.id
            WHERE r.id = %s GROUP BY s.direction ORDER BY 7 DESC
        """, (run_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def main():
    conn = dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database="trad_bot_backtest",
    )

    results = []
    total_t = time.time()

    print(f"{'='*100}")
    print(f"MOMENTUM_EXHAUSTION Optimization - {len(CONFIGS)} configs, {len(SYMBOLS)} coins, full year 2025")
    print(f"{'='*100}")
    print()

    for i, (label, extra) in enumerate(CONFIGS, 1):
        print(f"[{i:2d}/{len(CONFIGS)}] {label:30s} ", end="", flush=True)
        raw = run_one(label, extra)
        if raw["run_id"]:
            raw["metrics"] = fetch_metrics(conn, raw["run_id"])
            raw["by_symbol"] = fetch_by_symbol(conn, raw["run_id"])
            raw["by_regime"] = fetch_by_regime(conn, raw["run_id"])
            raw["by_direction"] = fetch_by_direction(conn, raw["run_id"])
        results.append(raw)

        m = raw.get("metrics", {})
        entries = m.get("entries", 0)
        tps = m.get("tps", 0)
        sls = m.get("sls", 0)
        wr = f"{round(tps/entries*100,1)}%" if entries > 0 else "N/A"
        print(f"set={raw['setups']:>5} ent={entries:>4} tp={tps:>3} sl={sls:>3} "
              f"avgR={raw['avg_r']:>7.4f} totR={raw['total_r']:>10.4f} "
              f"wr={wr:>6} [{raw['elapsed']:.0f}s]")

    total_elapsed = time.time() - total_t
    print(f"\nTotal time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")

    # ── Sort and display ranking ──
    successful = [r for r in results if r.get("metrics", {}).get("entries", 0) > 0]
    ranked = sorted(successful, key=lambda r: r.get("metrics", {}).get("total_r_all", 0), reverse=True)

    print(f"\n{'='*100}")
    print(f"RANKING BY TOTAL R (all entries)")
    print(f"{'='*100}")
    print(f"{'#':>3} {'Label':<30} {'Ent':>5} {'TP':>4} {'SL':>4} {'Wr%':>6} {'AvgR':>8} {'TotR':>10} {'MFE':>6} {'MAE':>6}")
    print("-" * 100)
    for i, r in enumerate(ranked, 1):
        m = r.get("metrics", {})
        entries = m.get("entries", 0)
        tps = m.get("tps", 0)
        wr = round(tps / entries * 100, 1) if entries > 0 else 0
        print(f"{i:>3} {r['label']:<30} {entries:>5} {m.get('tps',0):>4} {m.get('sls',0):>4} "
              f"{wr:>5.1f}% {m.get('avg_r_entry',0):>8.4f} "
              f"{m.get('total_r_all',0):>10.4f} {m.get('avg_mfe',0):>6.2f} {m.get('avg_mae',0):>6.2f}")

    # ── Best config detail ──
    if ranked:
        best = ranked[0]
        m = best.get("metrics", {})
        print(f"\n{'='*100}")
        print(f"BEST CONFIG: {best['label']}")
        print(f"{'='*100}")
        print(f"  CLI args: {best.get('cli_args', '')}")
        print(f"  Setups: {best['setups']}, Entries: {m.get('entries',0)}, TPs: {m.get('tps',0)}, SLs: {m.get('sls',0)}")
        print(f"  Avg R (entry): {m.get('avg_r_entry',0)}, Total R: {m.get('total_r_all',0)}")
        print(f"  Avg MFE: {m.get('avg_mfe',0)}, Avg MAE: {m.get('avg_mae',0)}")
        print(f"  Adjusted R: {m.get('avg_adjusted_r',0)}")
        wr = round(m.get('tps', 0) / m.get('entries', 1) * 100, 1) if m.get('entries', 0) > 0 else 0
        print(f"  Win rate: {wr}%")

        if best.get("by_symbol"):
            print(f"\n  Per-Symbol:")
            print(f"  {'Symbol':<18} {'Set':>5} {'Ent':>5} {'TP':>3} {'SL':>3} {'AvgR':>8} {'TotR':>10}")
            for s in best["by_symbol"]:
                print(f"  {s['symbol']:<18} {s.get('count',0):>5} {s.get('sum',0):>5} "
                      f"{s.get('sum_1',0):>3} {s.get('sum_2',0):>3} "
                      f"{s.get('avg_r',0):>8.4f} {s.get('sum_3',0):>10.4f}")

        if best.get("by_regime"):
            print(f"\n  Per-Regime:")
            print(f"  {'Regime':<16} {'Set':>5} {'Ent':>5} {'Win':>4} {'AvgR':>8} {'TotR':>10}")
            for rg in best["by_regime"]:
                print(f"  {str(rg.get('regime','')):<16} {rg.get('count',0):>5} {rg.get('sum',0):>5} "
                      f"{rg.get('sum_1',0):>4} {rg.get('avg_r',0):>8.4f} {rg.get('sum_2',0):>10.4f}")

        if best.get("by_direction"):
            print(f"\n  Per-Direction:")
            print(f"  {'Dir':<8} {'Set':>5} {'Ent':>5} {'TP':>3} {'SL':>3} {'AvgR':>8} {'TotR':>10}")
            for dd in best["by_direction"]:
                print(f"  {dd['direction']:<8} {dd.get('count',0):>5} {dd.get('sum',0):>5} "
                      f"{dd.get('sum_1',0):>3} {dd.get('sum_2',0):>3} "
                      f"{dd.get('avg_r',0):>8.4f} {dd.get('sum_3',0):>10.4f}")

    # ── Save JSON ──
    import json as j
    out_path = "exports/momentum_exhaustion_results.json"
    with open(out_path, "w") as f:
        # Strip by_symbol/regime/direction from JSON (too large)
        slim = []
        for r in results:
            s = {k: v for k, v in r.items()}
            slim.append(s)
        j.dump(slim, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
