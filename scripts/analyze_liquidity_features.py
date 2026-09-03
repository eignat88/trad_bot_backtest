"""Rank LIQUIDITY_REVERSAL feature buckets from persisted outcomes."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

from pg8000 import dbapi


def bucket(value: object, edges: tuple[float, ...]) -> str:
    value = float(value or 0.0)
    lower = 0.0
    for upper in edges:
        if value < upper:
            return f"[{lower:.2f},{upper:.2f})"
        lower = upper
    return f"[{lower:.2f},1.00]"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    connection = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"), host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), database=os.getenv("PGDATABASE", "trad_bot_backtest"))
    try:
        cursor = connection.cursor()
        cursor.execute("""SELECT s.direction, s.payload, o.entry_touched, o.result_r
                          FROM bt.setup s JOIN bt.outcome o ON o.setup_id=s.id
                         WHERE s.run_id=%s""", (args.run_id,))
        groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for direction, payload, entered, result_r in cursor.fetchall():
            if not entered:
                continue
            data = payload if isinstance(payload, dict) else json.loads(payload)
            features = data.get("features") or {}
            labels = {
                "volume": "spike" if features.get("volume_spike") else "no_spike",
                "regime_alignment": "aligned" if float(features.get("regime_alignment", 0)) >= 1 else "not_aligned",
                "sweep_depth": bucket(features.get("sweep_depth"), (0.10, 0.25, 0.50)),
                "rejection_strength": bucket(features.get("rejection_strength"), (0.25, 0.50, 0.75)),
                "rr_ratio": bucket(features.get("rr_ratio"), (0.50, 0.75, 0.90)),
                "volume_sweep": ("spike" if features.get("volume_spike") else "no_spike") + " / " + bucket(features.get("sweep_depth"), (0.10, 0.25, 0.50)),
            }
            for feature, label in labels.items():
                groups[(feature, direction, label)].append(float(result_r))
        print("feature | direction | bucket | trades | total_r | avg_r")
        for (feature, direction, label), values in sorted(groups.items()):
            print(f"{feature} | {direction} | {label} | {len(values)} | {sum(values):.4f} | {sum(values)/len(values):.4f}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
