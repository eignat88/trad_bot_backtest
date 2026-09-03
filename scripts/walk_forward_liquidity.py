"""Walk-forward evaluation of pre-registered LIQUIDITY_REVERSAL hypotheses.

The script never searches for a rule on its test slice.  It reports a fixed,
versioned hypothesis set against chronological train/test windows.  A report is
truly out-of-sample only when its supplied runs were not used to discover these
rules; otherwise it is a temporal-stability diagnostic.  Run it only after a
single unfiltered/enriched LIQUIDITY_REVERSAL backtest has been persisted.

Example:
    python -m scripts.walk_forward_liquidity --run-id <uuid> --from 2024-01-01 \
        --to 2026-09-01 --output exports/liquidity_reversal_walk_forward.md
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pg8000 import dbapi

from app.analytics.walk_forward import generate_walk_forward


Rule = tuple[str, str, Callable[[dict[str, Any]], bool]]


def _number(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# These hypotheses are deliberately fixed from the 2025 attribution report.
# Do not add, remove, or rank rules after inspecting test windows.
RULES: tuple[Rule, ...] = (
    ("baseline", "LONG liquidity-reversal entries without post-scan feature filters", lambda r: True),
    ("swing_low", "level_type=swing_low", lambda r: r.get("level_type") == "swing_low"),
    ("shallow_swing", "swing_low and sweep_depth_atr < 0.25", lambda r: r.get("level_type") == "swing_low" and _number(r, "sweep_depth_atr") < 0.25),
    ("high_volume", "swing_low and volume_ratio_20 >= 3.0", lambda r: r.get("level_type") == "swing_low" and _number(r, "volume_ratio_20") >= 3.0),
    ("us_rejection", "swing_low, US session, close_location < 0.6", lambda r: r.get("level_type") == "swing_low" and r.get("session") == "us" and _number(r, "close_location") < 0.6),
    ("full_hypothesis", "swing_low, shallow sweep, high volume, US rejection", lambda r: r.get("level_type") == "swing_low" and _number(r, "sweep_depth_atr") < 0.25 and _number(r, "volume_ratio_20") >= 3.0 and r.get("session") == "us" and _number(r, "close_location") < 0.6),
)


def parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def fetch_rows(connection, run_ids: list[str]) -> list[dict[str, Any]]:
    placeholders = ", ".join(["%s"] * len(run_ids))
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"""SELECT s.detected_at, s.direction, s.payload, o.entry_touched,
                       o.result_r
                  FROM bt.setup s
                  JOIN bt.outcome o ON o.setup_id = s.id
                 WHERE s.run_id IN ({placeholders})
                 ORDER BY s.detected_at""",
            run_ids,
        )
        rows: list[dict[str, Any]] = []
        for detected_at, direction, payload, entry_touched, result_r in cursor.fetchall():
            if isinstance(payload, str):
                payload = json.loads(payload)
            features = (payload or {}).get("features") or {}
            if isinstance(features, str):
                features = json.loads(features)
            enriched = dict(features.get("enriched") or {})
            enriched.update(
                detected_at=detected_at.astimezone(timezone.utc),
                direction=direction,
                entry_touched=bool(entry_touched),
                result_r=float(result_r or 0.0),
            )
            rows.append(enriched)
        return rows
    finally:
        cursor.close()


def metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    entered = [r for r in rows if r["entry_touched"]]
    values = [r["result_r"] for r in entered]
    gross_profit = sum(x for x in values if x > 0)
    gross_loss = -sum(x for x in values if x < 0)
    return {
        "setups": len(rows),
        "trades": len(entered),
        "total_r": round(sum(values), 4),
        "avg_r": round(sum(values) / len(values), 4) if values else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else 0.0,
        "win_rate": round(sum(x > 0 for x in values) / len(values), 4) if values else 0.0,
    }


def evaluate_windows(rows: list[dict[str, Any]], start: datetime, end: datetime, train_months: int, test_months: int, step_months: int) -> list[dict[str, Any]]:
    windows = generate_walk_forward(start, end, train_months=train_months, test_months=test_months, step_months=step_months)
    if not windows:
        raise ValueError("no complete walk-forward windows; extend the date range or reduce window lengths")
    report: list[dict[str, Any]] = []
    for window in windows:
        train = [r for r in rows if window.train_start <= r["detected_at"] < window.train_end]
        test = [r for r in rows if window.test_start <= r["detected_at"] < window.test_end]
        for name, description, predicate in RULES:
            report.append({
                "rule": name,
                "description": description,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "test_start": window.test_start,
                "test_end": window.test_end,
                "train": metrics([r for r in train if predicate(r)]),
                "test": metrics([r for r in test if predicate(r)]),
            })
    return report


def render_markdown(results: list[dict[str, Any]], run_ids: list[str]) -> str:
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_rule[result["rule"]].append(result)
    lines = [
        "# LIQUIDITY_REVERSAL — Walk-Forward Report",
        "",
        f"Runs: {', '.join(run_ids)}",
        "",
        "No test-window optimisation or rule selection is performed. This report is out-of-sample only if "
        "the supplied runs were not used to discover the fixed rules; otherwise it is a temporal-stability diagnostic.",
        "",
    ]
    for rule, items in by_rule.items():
        lines.extend([f"## {rule}", "", items[0]["description"], "", "| Test window | Train trades | Train Avg R | Test trades | Test Avg R | Test PF | Test Total R |", "|---|---:|---:|---:|---:|---:|---:|"])
        for item in items:
            train, test = item["train"], item["test"]
            label = f"{item['test_start']:%Y-%m-%d}–{item['test_end']:%Y-%m-%d}"
            lines.append(f"| {label} | {train['trades']} | {train['avg_r']:+.4f} | {test['trades']} | {test['avg_r']:+.4f} | {test['profit_factor']:.2f} | {test['total_r']:+.2f} |")
        tests = [item["test"] for item in items]
        total_trades = sum(int(x["trades"]) for x in tests)
        total_r = sum(float(x["total_r"]) for x in tests)
        positive = sum(float(x["avg_r"]) > 0 for x in tests)
        lines.extend(["", f"Out-of-sample summary: {total_trades} trades, {total_r:+.2f}R, {positive}/{len(tests)} positive test windows.", ""])
    lines.extend([
        "## Interpretation guardrails",
        "",
        "- A rule with fewer than 30 aggregate OOS trades is inconclusive.",
        "- Positive OOS performance concentrated in one symbol or one window is not a tradable edge.",
        "- Treat this report as validation of hypotheses, not a parameter-search result.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward report for fixed LIQUIDITY_REVERSAL hypotheses")
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True, help="exclusive endpoint")
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--test-months", type=int, default=1)
    parser.add_argument("--step-months", type=int, default=1)
    parser.add_argument("--db-name", default=os.getenv("PGDATABASE", "trad_bot_backtest"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    start, end = parse_date(args.start), parse_date(args.end)
    if start >= end:
        parser.error("--from must be before --to")
    connection = dbapi.connect(user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"), host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5432")), database=args.db_name)
    try:
        rows = [r for r in fetch_rows(connection, args.run_id) if r["direction"] == "LONG"]
    finally:
        connection.close()
    if not rows:
        raise ValueError("no LONG rows found for supplied run IDs")
    report = render_markdown(evaluate_windows(rows, start, end, args.train_months, args.test_months, args.step_months), args.run_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
