"""Historical market-data provider that prevents look-ahead bias."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Candle:
    timestamp: int  # UTC epoch milliseconds; open time
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleRepository(Protocol):
    def fetch_candles(self, symbol: str, timeframe: str, start_ms: int | None, end_ms: int) -> Sequence[Candle]: ...


class HistoricalClock:
    """Mutable simulation clock; scanners may only observe data up to ``now``."""
    def __init__(self, now: datetime) -> None:
        self.set(now)

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def now_ms(self) -> int:
        return int(self._now.timestamp() * 1000)

    def set(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("HistoricalClock requires timezone-aware UTC datetimes")
        self._now = value.astimezone(timezone.utc)


class InMemoryCandleRepository:
    def __init__(self, candles: Mapping[tuple[str, str], Sequence[Candle]]) -> None:
        self._candles = {key: tuple(sorted(value, key=lambda c: c.timestamp)) for key, value in candles.items()}

    def fetch_candles(self, symbol: str, timeframe: str, start_ms: int | None, end_ms: int) -> Sequence[Candle]:
        return tuple(c for c in self._candles.get((symbol, timeframe), ()) if (start_ms is None or c.timestamp >= start_ms) and c.timestamp <= end_ms)


class PostgresHistoricalDataProvider:
    """Read-only provider over ``market.candle`` using a caller supplied connection."""
    def __init__(self, connection, clock: HistoricalClock) -> None:
        self.connection, self.clock = connection, clock

    def get_candles(self, symbol: str, timeframe: str, *, limit: int = 500, start: datetime | None = None) -> tuple[Candle, ...]:
        end_ms = self.clock.now_ms
        start_ms = int(start.timestamp() * 1000) if start else None
        sql = """
            SELECT EXTRACT(EPOCH FROM c.open_time) * 1000, c.open, c.high, c.low, c.close, c.volume
            FROM market.candle c JOIN market.instrument i ON i.id = c.instrument_id
            WHERE i.symbol = %s AND c.timeframe = %s AND c.open_time <= to_timestamp(%s / 1000.0)
              AND (%s IS NULL OR c.open_time >= to_timestamp(%s / 1000.0))
            ORDER BY c.open_time DESC LIMIT %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(sql, (symbol, timeframe, end_ms, start_ms, start_ms, limit))
            rows = cursor.fetchall()
        return tuple(Candle(int(row[0]), *map(float, row[1:])) for row in reversed(rows))


class HistoricalDataProvider:
    """Provider facade shared by context builders and scanner adapters."""
    def __init__(self, repository: CandleRepository, clock: HistoricalClock) -> None:
        self.repository, self.clock = repository, clock

    def get_candles(self, symbol: str, timeframe: str, *, limit: int = 500) -> tuple[Candle, ...]:
        candles = self.repository.fetch_candles(symbol, timeframe, None, self.clock.now_ms)
        return tuple(candles[-limit:])
