"""Compatibility layer: production scanners remain the single source of strategy logic."""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Callable, Protocol
from app.data.historical_provider import HistoricalDataProvider

class Scanner(Protocol):
    def __call__(self, symbol: str, provider: HistoricalDataProvider) -> list[object]: ...


def add_production_project(production_root: str | Path) -> None:
    """Make the existing ``trad_bot/app`` importable without copying scanner code."""
    root = str(Path(production_root).resolve())
    if root not in sys.path: sys.path.insert(0, root)


def production_context_adapter(context_builder: Callable[..., object], symbol: str, provider: HistoricalDataProvider) -> object:
    """Call a production context builder with only closed historical candles.

    The supplied builder owns the scanner-specific indicators and levels.  Its input
    is bounded by ``provider.clock`` so a future candle is never exposed.
    """
    return context_builder(
        symbol=symbol,
        candles_5m=provider.get_candles(symbol, "5m"),
        candles_15m=provider.get_candles(symbol, "15m"),
        candles_1h=provider.get_candles(symbol, "1h"),
        candles_4h=provider.get_candles(symbol, "4h"),
        evaluated_at=provider.clock.now,
    )


class ProductionScannerAdapter:
    """Runs a production scanner/orchestrator against a historical context factory."""
    def __init__(self, scanner: object, context_builder: Callable[..., object]) -> None:
        self.scanner, self.context_builder = scanner, context_builder

    def scan(self, symbol: str, provider: HistoricalDataProvider) -> list[object]:
        context = production_context_adapter(self.context_builder, symbol, provider)
        if hasattr(self.scanner, "scan"):
            return list(self.scanner.scan(context))
        if hasattr(self.scanner, "scan_all"):
            return list(self.scanner.scan_all(context))
        raise TypeError("scanner must provide scan(context) or scan_all(context)")
