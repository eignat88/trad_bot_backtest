"""Build one leakage-free row per setup for edge research.

This module intentionally accepts plain mappings so it can consume exported backtest
rows as well as database records.  Feature values must be computed at ``signal_time``;
future outcomes are attached only after the snapshot has been frozen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping


Scalar = str | int | float | bool | None


def flatten_features(values: Mapping[str, Any], *, prefix: str = "") -> dict[str, Scalar]:
    """Flatten nested scanner/context feature mappings into stable column names.

    Sequences and arbitrary objects are deliberately excluded: retaining them would
    produce a non-tabular, difficult-to-version research dataset.
    """
    flattened: dict[str, Scalar] = {}
    for key, value in values.items():
        name = f"{prefix}_{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            flattened.update(flatten_features(value, prefix=name))
        elif value is None or isinstance(value, (str, int, float, bool)):
            flattened[name] = value
    return flattened


@dataclass(frozen=True)
class EdgeRow:
    """Canonical mart row: snapshot dimensions/features plus independent outcomes."""

    setup_id: str
    scanner_name: str
    scanner_version: str | None
    symbol: str
    direction: str
    signal_time: datetime
    features: Mapping[str, Scalar]
    outcomes: Mapping[str, Scalar]

    def as_dict(self) -> dict[str, Scalar]:
        return {
            "setup_id": self.setup_id,
            "scanner_name": self.scanner_name,
            "scanner_version": self.scanner_version,
            "symbol": self.symbol,
            "direction": self.direction,
            "signal_time": self.signal_time,
            **self.features,
            **self.outcomes,
        }


def build_edge_rows(
    setups: Iterable[Mapping[str, Any]],
    outcomes_by_setup: Mapping[str, Mapping[str, Scalar]],
    *,
    feature_set_version: str,
) -> tuple[EdgeRow, ...]:
    """Create a versioned mart dataset from point-in-time setup snapshots.

    ``setups`` must provide the six identifying fields plus optional ``features`` and
    ``market_context`` mappings.  Missing independent outcomes are allowed; this is
    useful when a signal has not yet reached its longest evaluation horizon.
    """
    rows: list[EdgeRow] = []
    required = ("setup_id", "scanner_name", "symbol", "direction", "signal_time")
    for setup in setups:
        missing = [name for name in required if name not in setup]
        if missing:
            raise ValueError(f"setup missing required fields: {', '.join(missing)}")
        signal_time = setup["signal_time"]
        if not isinstance(signal_time, datetime) or signal_time.tzinfo is None:
            raise ValueError("signal_time must be timezone-aware")
        for timestamp_field in ("snapshot_at", "source_max_time"):
            timestamp = setup.get(timestamp_field)
            if timestamp is not None and (not isinstance(timestamp, datetime) or timestamp.tzinfo is None or timestamp > signal_time):
                raise ValueError(f"{timestamp_field} must be timezone-aware and no later than signal_time")
        setup_id = str(setup["setup_id"])
        features = flatten_features(dict(setup.get("features") or {}))
        features.update(flatten_features(dict(setup.get("market_context") or {}), prefix="market"))
        features["feature_set_version"] = feature_set_version
        rows.append(EdgeRow(
            setup_id=setup_id,
            scanner_name=str(setup["scanner_name"]),
            scanner_version=str(setup["scanner_version"]) if setup.get("scanner_version") is not None else None,
            symbol=str(setup["symbol"]), direction=str(setup["direction"]),
            signal_time=signal_time,
            features=features,
            outcomes=dict(outcomes_by_setup.get(setup_id, {})),
        ))
    return tuple(rows)
