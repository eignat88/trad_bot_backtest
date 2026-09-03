"""Analyze all backtest runs and produce a comparative ranking report."""
from __future__ import annotations
import os
import sys
from pg8000 import dbapi


def connect():
    return dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("PGDATABASE", "trad_bot_backtest"),
    )


def fetch_all_runs(connection):
    """Fetch metrics for all runs that have TREND_PULLBACK setups."""
    cur = connection.cursor()
    try:
        cur.execute("""
            SELECT
                r.id::text as run_id,
                r.execution_profile,
                COUNT(s.id) as setups,
                SUM(CASE WHEN o.entry_touched THEN 1 ELSE 0 END) as entries,
                SUM(CASE WHEN o.first_event IN ('TP1','TP2') THEN 1 ELSE 0 END) as tps,
                SUM(CASE WHEN o.first_event = 'SL' THEN 1 ELSE 0 END) as sls,
                SUM(CASE WHEN o.first_event LIKE 'EXPIRED' THEN 1 ELSE 0 END) as expired,
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
            WHERE s.scanner_name = 'TREND_PULLBACK'
            GROUP BY r.id, r.execution_profile
            ORDER BY total_r_entries DESC
        """)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def format_label(profile):
    """Create a human-readable label from execution profile."""
    if profile is None:
        return "unknown"
    parts = []
    pt = profile.get("pullback_tolerance")
    rct = profile.get("rsi_cool_threshold")
    tf = profile.get("signal_timeframe", "5m")
    tr = profile.get("target_r")
    sr = profile.get("skip_range")
    mpq = profile.get("max_pullback_quality")
    be = profile.get("expire_at_breakeven")
    mb = profile.get("max_bars")

    if pt is not None:
        parts.append(f"pt={pt}")
    if rct is not None:
        parts.append(f"rct={rct}")
    if tf and tf != "5m":
        parts.append(f"tf={tf}")
    if tr is not None:
        parts.append(f"tr={tr}")
    if sr:
        parts.append("skip_range")
    if mpq is not None:
        parts.append(f"mpq={mpq}")
    if be:
        parts.append("expire_be")
    if mb and mb != 48:
        parts.append(f"bars={mb}")
    return " | ".join(parts) if parts else "defaults"


def main():
    conn = connect()
    try:
        runs = fetch_all_runs(conn)
        print(f"Total runs found: {len(runs)}\n")

        # Header
        print(f"{'Label':<45} {'Set':>5} {'Ent':>5} {'TP':>4} {'SL':>4} {'Exp':>4} {'WR%':>6} {'AvgR':>8} {'TotR':>10} {'MFE':>6} {'MAE':>6}")
        print("-" * 120)

        for run in runs:
            label = format_label(run.get("execution_profile"))
            entries = run["entries"] or 0
            tps = run["tps"] or 0
            wr = round(tps / entries * 100, 1) if entries > 0 else 0
            avg_r = float(run["avg_r_entry"]) if run["avg_r_entry"] else 0
            total_r = float(run["total_r_entries"]) if run["total_r_entries"] else 0
            mfe = float(run["avg_mfe"]) if run["avg_mfe"] else 0
            mae = float(run["avg_mae"]) if run["avg_mae"] else 0

            marker = ""
            if total_r > 0:
                marker = " +"
            elif total_r < -50:
                marker = " !!"

            print(f"{label:<45} {run['setups']:>5} {entries:>5} {tps:>4} {run['sls']:>4} {run['expired']:>4} {wr:>5.1f}% {avg_r:>8.4f} {total_r:>10.2f} {mfe:>6.3f} {mae:>6.3f}{marker}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
