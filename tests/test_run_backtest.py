from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from scripts.run_backtest import finalized_candidate, parse_range, resample


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Candidate:
    setup_id: object = uuid4()
    signal_candle_open_time: int = 0
    detected_at: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc)


def test_finalized_candidate_has_stable_historical_identity():
    detected_at = datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)
    candidate = finalized_candidate(
        Candidate(), signal_candle_open_time=1_735_689_840_000, detected_at=detected_at
    )

    assert candidate.signal_candle_open_time == 1_735_689_840_000
    assert candidate.detected_at == detected_at


def test_resample_requires_a_complete_bucket():
    candles = tuple(Candle(i * 60_000, 1, i + 2, i, i + 1, 1) for i in range(6))

    rows = resample(candles, 300_000, Candle)

    assert len(rows) == 1
    assert rows[0] == Candle(0, 1, 6, 0, 5, 5)


def test_date_only_end_is_exclusive_next_midnight():
    assert parse_range("2025-06-30", is_end=True) == datetime(2025, 7, 1, tzinfo=timezone.utc)
