"""PostgreSQL writers for frozen research snapshots."""
from __future__ import annotations

import json
from typing import Any, Mapping

from .outcomes import SignalPathOutcome


def persist_signal_outcome(connection: Any, *, setup_id: str, evaluated_at: object, outcome: SignalPathOutcome) -> None:
    """Upsert an independently calculated signal path outcome for one setup."""
    values = outcome.as_dict()
    columns = ["setup_id", "evaluated_at", *values]
    cursor = connection.cursor()
    try:
        placeholders = ", ".join(["%s"] * len(columns))
        assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns[2:])
        cursor.execute(
            f"INSERT INTO dds.signal_outcome ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT (setup_id) DO UPDATE SET evaluated_at = EXCLUDED.evaluated_at, {assignments}",
            [setup_id, evaluated_at, *values.values()],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def persist_feature_snapshot(connection: Any, *, setup_id: str, signal_time: object, feature_set_version: str,
                             scanner_version: str | None, features: Mapping[str, object], market_context_id: str | None = None) -> None:
    """Persist known wide columns and retain all additional scalar features in JSONB.

    The JSONB payload preserves experimental fields while stable/high-use fields can
    later be promoted to dedicated wide columns through a migration.
    """
    allowed = {
        "ema20_distance_pct", "ema50_distance_pct", "ema200_distance_pct", "ema20_slope", "ema50_slope", "adx", "trend_strength",
        "rsi_14", "rsi_delta_3", "macd_hist", "macd_hist_delta", "roc_5", "roc_20", "atr_pct", "atr_percentile_30d",
        "bb_width", "bb_width_percentile", "realized_volatility", "volume_ratio_20", "volume_zscore", "quote_volume", "spread_bps",
        "orderbook_imbalance", "liquidity_score", "body_pct", "upper_wick_pct", "lower_wick_pct", "distance_to_support_atr",
        "distance_to_resistance_atr", "range_position", "symbol_return_rank_1h", "symbol_return_rank_4h", "volume_rank",
        "volatility_rank", "relative_strength_btc", "relative_strength_market", "scanner_score", "risk_distance_atr",
        "target_distance_atr", "rr_planned", "confirmation_count", "hour_of_day", "day_of_week",
    }
    selected = {key: value for key, value in features.items() if key in allowed}
    columns = ["setup_id", "signal_time", "feature_set_version", "scanner_version", "market_context_id", *selected, "features"]
    values = [setup_id, signal_time, feature_set_version, scanner_version, market_context_id, *selected.values(), json.dumps(features, default=str)]
    update_columns = [column for column in columns if column != "setup_id"]
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"INSERT INTO dds.setup_feature_snapshot ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
            f"ON CONFLICT (setup_id) DO UPDATE SET {', '.join(f'{column} = EXCLUDED.{column}' for column in update_columns)}",
            values,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
