"""Feature attribution report for LIQUIDITY_REVERSAL setups.

Reads persisted bt.setup + bt.outcome rows, extracts enriched features,
and produces per-bin metrics for every prioritised feature dimension.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict
from typing import Any

from pg8000 import dbapi


def connect(db_name: str):
    return dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database=db_name,
    )


def fetch_runs(connection, run_ids: list[str]) -> list[dict[str, Any]]:
    placeholders = ", ".join(["%s"] * len(run_ids))
    cur = connection.cursor()
    try:
        cur.execute(f"""
            SELECT r.id::text, r.execution_profile, r.start_at, r.end_at,
                   s.id::text, s.symbol, s.direction, s.regime, s.detected_at,
                   s.score, s.payload,
                   o.entry_touched, o.first_event, o.result_r, o.mfe_r, o.mae_r
            FROM bt.run r
            JOIN bt.setup s ON s.run_id = r.id
            JOIN bt.outcome o ON o.setup_id = s.id
            WHERE r.id IN ({placeholders})
            ORDER BY r.id, s.detected_at
        """, run_ids)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def extract_enriched(row: dict) -> dict[str, Any]:
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    features = payload.get("features") or {}
    if isinstance(features, str):
        features = json.loads(features)
    enriched = features.get("enriched") or {}
    enriched["symbol"] = row.get("symbol")
    enriched["direction"] = row.get("direction")
    enriched["regime"] = row.get("regime")
    enriched["first_event"] = row.get("first_event")
    enriched["result_r"] = float(row.get("result_r") or 0)
    enriched["mfe_r"] = float(row.get("mfe_r") or 0)
    enriched["mae_r"] = float(row.get("mae_r") or 0)
    enriched["entry_touched"] = bool(row.get("entry_touched"))
    enriched["month"] = str(row.get("detected_at", ""))[:7] if row.get("detected_at") else ""
    return enriched


# ---------------------------------------------------------------------------
# Bin definitions – one entry per priority feature
# ---------------------------------------------------------------------------
BIN_DEFS: dict[str, dict] = {
    "level_type": {
        "priority": 1,
        "bins": lambda v: v if v else "unknown",
        "description": "Which liquidity level was swept (swing_low, day, week)",
    },
    "sweep_depth_atr": {
        "priority": 2,
        "bins": lambda v: _quantile_bucket(float(v or 0), (0.1, 0.25, 0.5, 1.0, 2.0, 5.0)),
        "description": "Sweep depth normalised by ATR (comparable across BTC/SUI/PEPE)",
    },
    "volume_ratio_20": {
        "priority": 3,
        "bins": lambda v: _quantile_bucket(float(v or 0), (0.5, 0.8, 1.2, 2.0, 3.0)),
        "description": "Volume / SMA(20) on 5m bar",
    },
    "close_location": {
        "priority": 3,
        "bins": lambda v: _quantile_bucket(float(v or 0.5), (0.2, 0.4, 0.6, 0.8)),
        "description": "Where close sits within the bar (0=low, 1=high)",
    },
    "atr_percentile": {
        "priority": 4,
        "bins": lambda v: _quantile_bucket(float(v or 0.5), (0.2, 0.4, 0.6, 0.8)),
        "description": "ATR rank over recent 100 1h bars",
    },
    "realized_volatility": {
        "priority": 4,
        "bins": lambda v: _quantile_bucket(float(v or 0), (0.5, 1.0, 2.0, 4.0)),
        "description": "Realised vol over last 60 5m bars (annualised)",
    },
    "regime_alignment": {
        "priority": 5,
        "bins": lambda v: "aligned" if float(v or 0) >= 1 else "not_aligned",
        "description": "Does trade direction align with market regime?",
    },
    "btc_regime": {
        "priority": 6,
        "bins": lambda v: v if v else "unknown",
        "description": "BTC market regime at signal time",
    },
    "btc_return_15m": {
        "priority": 6,
        "bins": lambda v: _quantile_bucket(float(v or 0), (-0.005, -0.002, 0.002, 0.005)),
        "description": "BTC return over last 15 minutes",
    },
    "ema200_side": {
        "priority": 7,
        "bins": lambda v: v if v else "unknown",
        "description": "Is entry above or below EMA200?",
    },
    "session": {
        "priority": 10,
        "bins": lambda v: v if v else "unknown",
        "description": "UTC session: asia / europe / us / late_us",
    },
}


def _quantile_bucket(value: float, edges: tuple[float, ...]) -> str:
    lower = float("-inf")
    for upper in edges:
        if value < upper:
            return f"< {upper}"
        lower = upper
    return f">= {lower}"


def compute_metrics(rows: list[dict]) -> dict[str, Any]:
    entered = [r for r in rows if r.get("entry_touched")]
    trades = len(entered)
    results = [float(r.get("result_r", 0)) for r in entered]
    total = sum(results)
    avg = total / trades if trades else 0.0
    wins = sum(1 for r in results if r > 0)
    losses = sum(1 for r in results if r < 0)
    win_rate = wins / trades if trades else 0.0

    gp = sum(r for r in results if r > 0)
    gl = -sum(r for r in results if r < 0)
    pf = gp / gl if gl else 0.0

    # Median
    sorted_r = sorted(results)
    n = len(sorted_r)
    median = (sorted_r[n // 2] + sorted_r[(n - 1) // 2]) / 2 if n else 0.0

    # Max drawdown (R)
    equity = peak = max_dd = 0.0
    for r in results:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)

    # Average MFE/MAE
    avg_mfe = sum(float(r.get("mfe_r", 0)) for r in entered) / trades if trades else 0.0
    avg_mae = sum(float(r.get("mae_r", 0)) for r in entered) / trades if trades else 0.0

    # Event counts
    events = defaultdict(int)
    for r in entered:
        events[r.get("first_event", "?")] += 1

    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "total_r": round(total, 4),
        "avg_r": round(avg, 4),
        "median_r": round(median, 4),
        "profit_factor": round(pf, 4),
        "max_dd_r": round(max_dd, 4),
        "avg_mfe_r": round(avg_mfe, 4),
        "avg_mae_r": round(avg_mae, 4),
        "events": dict(events),
    }


def print_table(title: str, rows: list[dict], columns: list[str]):
    if not rows:
        return
    header = f"\n{'=' * 80}\n{title}\n{'=' * 80}"
    print(header)
    widths = {}
    for col in columns:
        widths[col] = max(len(col), max(len(str(r.get(col, ""))) for r in rows))
    fmt = "  ".join(f"{{:<{widths[c]}}}" for c in columns)
    print(fmt.format(*columns))
    print("  ".join("-" * widths[c] for c in columns))
    for r in rows:
        print(fmt.format(*[str(r.get(c, "")) for c in columns]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Feature attribution report for LIQUIDITY_REVERSAL")
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--direction", choices=("LONG", "SHORT", "BOTH"), default="BOTH")
    parser.add_argument("--by-symbol", action="store_true", help="Also print per-symbol breakdowns")
    args = parser.parse_args()

    conn = connect(args.db_name)
    try:
        rows = fetch_runs(conn, args.run_id)
    finally:
        conn.close()

    enriched = [extract_enriched(r) for r in rows]

    # Filter by direction
    if args.direction != "BOTH":
        enriched = [r for r in enriched if r.get("direction") == args.direction]

    # Overall metrics
    overall = compute_metrics(enriched)
    print(f"\n{'#' * 80}")
    print(f"# FEATURE ATTRIBUTION REPORT — LIQUIDITY_REVERSAL")
    print(f"# Runs: {', '.join(args.run_id)}")
    print(f"# Direction: {args.direction}")
    print(f"# Total setups: {len(enriched)} | Entries: {overall['trades']}")
    print(f"# Overall: PF={overall['profit_factor']}  AvgR={overall['avg_r']}  "
          f"TotalR={overall['total_r']}  MaxDD={overall['max_dd_r']}  "
          f"WR={overall['win_rate']:.1%}")
    print(f"{'#' * 80}")

    # Per-feature attribution tables
    columns = ["bin", "trades", "win_rate", "avg_r", "median_r", "profit_factor", "total_r", "max_dd_r", "avg_mfe_r", "avg_mae_r"]

    for feature_name, config in sorted(BIN_DEFS.items(), key=lambda x: x[1]["priority"]):
        bin_fn = config["bins"]
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in enriched:
            value = r.get(feature_name)
            bin_label = bin_fn(value)
            groups[str(bin_label)].append(r)

        table_rows = []
        for bin_label, bin_rows in sorted(groups.items()):
            m = compute_metrics(bin_rows)
            table_rows.append({
                "bin": bin_label,
                **m,
            })
            # Remove events from display
            table_rows[-1].pop("events", None)

        # Sort by avg_r descending
        table_rows.sort(key=lambda x: x.get("avg_r", 0), reverse=True)

        print_table(
            f"[P{config['priority']}] {feature_name}: {config['description']}",
            table_rows,
            columns,
        )

    # Per-symbol breakdown if requested
    if args.by_symbol:
        symbols = sorted(set(r.get("symbol", "?") for r in enriched))
        for sym in symbols:
            sym_rows = [r for r in enriched if r.get("symbol") == sym]
            m = compute_metrics(sym_rows)
            print(f"\n  {sym}: trades={m['trades']} PF={m['profit_factor']} AvgR={m['avg_r']} TotalR={m['total_r']} WR={m['win_rate']:.1%}")

    # Per-month stability check
    months = sorted(set(r.get("month", "") for r in enriched if r.get("month")))
    if months:
        print_table(
            "Monthly stability",
            [
                {"month": m, **compute_metrics([r for r in enriched if r.get("month") == m])}
                for m in months
            ],
            ["month", "trades", "win_rate", "avg_r", "profit_factor", "total_r", "max_dd_r"],
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
