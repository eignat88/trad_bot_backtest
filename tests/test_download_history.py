from datetime import datetime, timezone

from scripts import download_history


def test_download_merges_and_sorts_concurrent_batches(monkeypatch):
    requested = []

    def fake_fetch(symbol, interval, start_ms, end_ms):
        requested.append((symbol, interval, start_ms, end_ms))
        return [[str(start_ms + 60_000), "1", "1", "1", "1", "1", "1"], [str(start_ms), "1", "1", "1", "1", "1", "1"]]

    monkeypatch.setattr(download_history, "fetch_batch", fake_fetch)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc)

    rows = download_history.download("BTCUSDT", "1m", start, end, workers=2)

    assert [int(row[0]) for row in rows] == [int(start.timestamp() * 1000), int(start.timestamp() * 1000) + 60_000]
    assert len(requested) == 1
