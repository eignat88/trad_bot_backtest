"""Chronological train/test windows; no random shuffling of market data."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from dateutil.relativedelta import relativedelta

@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: datetime; train_end: datetime; test_start: datetime; test_end: datetime

def generate_walk_forward(start: datetime, end: datetime, *, train_months: int = 6, test_months: int = 1, step_months: int = 1) -> tuple[WalkForwardWindow, ...]:
    if train_months <= 0 or test_months <= 0 or step_months <= 0: raise ValueError("window sizes must be positive")
    windows = []; cursor = start
    while (test_end := cursor + relativedelta(months=train_months + test_months)) <= end:
        train_end = cursor + relativedelta(months=train_months)
        windows.append(WalkForwardWindow(cursor, train_end, train_end, test_end))
        cursor += relativedelta(months=step_months)
    return tuple(windows)
