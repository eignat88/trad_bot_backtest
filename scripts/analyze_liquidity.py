"""Summarize persisted LIQUIDITY_REVERSAL research runs."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

from pg8000 import dbapi


def connect():
    return dbapi.connect(
        user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"),
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("PGDATABASE", "trad_bot_backtest"),
    )


def metrics(rows):
    setups = len(rows)
    entered = [r for r in rows if r[3]]
    results = [float(r[4]) for r in entered]
    total = sum(results)
    average = total / len(results) if results else 0.0
    wins = sum(r > 0 for r in results)
    losses = sum(r < 0 for r in results)
    gross_profit = sum(r for r in results if r > 0)
    gross_loss = -sum(r for r in results if r < 0)
    pf = gross_profit / gross_loss if gross_loss else 0.0
    equity = peak = max_drawdown = 0.0
    for result in results:
        equity += result
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return {
        "setups": setups, "entries": len(entered), "wins": wins, "losses": losses,
        "entry_rate": len(entered) / setups if setups else 0.0,
        "win_rate": wins / len(entered) if entered else 0.0,
        "total_r": total, "avg_r": average, "profit_factor": pf,
        "max_drawdown_r": max_drawdown,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_ids", nargs="+")
    args = parser.parse_args()
    conn = connect()
    try:
        cur = conn.cursor()
        placeholders = ", ".join(["%s"] * len(args.run_ids))
        cur.execute(
            f"""SELECT r.id::text, r.execution_profile, s.symbol, s.direction,
                       o.entry_touched, o.result_r, s.detected_at
                  FROM bt.run r JOIN bt.setup s ON s.run_id=r.id
                  JOIN bt.outcome o ON o.setup_id=s.id
                 WHERE r.id IN ({placeholders})
                 ORDER BY r.id, s.detected_at""",
            args.run_ids,
        )
        grouped = defaultdict(list)
        profiles = {}
        for run_id, profile, symbol, direction, entered, result_r, detected_at in cur.fetchall():
            profiles[run_id] = profile if isinstance(profile, dict) else json.loads(profile)
            grouped[run_id].append((symbol, direction, detected_at, entered, result_r))
        for run_id in args.run_ids:
            rows = grouped[run_id]
            result = metrics(rows)
            profile = profiles.get(run_id, {})
            print(json.dumps({"run_id": run_id, "profile": profile, "all": result}, default=str))
            for direction in ("LONG", "SHORT"):
                subset = [r for r in rows if r[1] == direction]
                if subset:
                    print(json.dumps({"direction": direction, **metrics(subset)}, default=str))
            by_symbol = []
            for symbol in sorted({r[0] for r in rows}):
                result_symbol = metrics([r for r in rows if r[0] == symbol])
                by_symbol.append({"symbol": symbol, **result_symbol})
            print(json.dumps({"by_symbol": by_symbol}, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
