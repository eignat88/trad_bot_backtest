from datetime import datetime, timezone

from scripts.walk_forward_liquidity import evaluate_windows


def _row(when: str, result: float, **features):
    return {
        "detected_at": datetime.fromisoformat(when).replace(tzinfo=timezone.utc),
        "direction": "LONG",
        "entry_touched": True,
        "result_r": result,
        **features,
    }


def test_evaluate_windows_is_chronological_and_uses_fixed_rules():
    rows = [
        _row("2025-01-15T00:00:00", 1.0, level_type="swing_low", sweep_depth_atr=0.1, volume_ratio_20=3.5, session="us", close_location=0.2),
        _row("2025-02-15T00:00:00", -1.0, level_type="previous_day_low", sweep_depth_atr=0.5, volume_ratio_20=1.0, session="asia", close_location=0.9),
        _row("2025-03-15T00:00:00", 2.0, level_type="swing_low", sweep_depth_atr=0.1, volume_ratio_20=3.5, session="us", close_location=0.2),
    ]

    results = evaluate_windows(
        rows,
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 4, 1, tzinfo=timezone.utc),
        train_months=2,
        test_months=1,
        step_months=1,
    )

    baseline = next(item for item in results if item["rule"] == "baseline")
    assert baseline["train"]["trades"] == 2
    assert baseline["test"]["trades"] == 1
    assert baseline["test"]["total_r"] == 2.0
    assert all(item["test_start"] >= item["train_end"] for item in results)
