# trad_bot_backtest (trad_bot_lab MVP)

Local research environment for historical testing and optimization of the **existing** `trad_bot` scanner logic.  It deliberately contains no copied scanner implementation: `app.scanners.adapters.ProductionScannerAdapter` runs a production scanner with a clock-bounded historical provider.

## Guarantees

- Canonical 1m OHLCV data and deterministic higher-timeframe resampling.
- `HistoricalClock` plus `HistoricalDataProvider`: scanner code can never request candles beyond simulation time.
- Fast Level 1 flow: `scanner → setup → outcome → R metrics` with conservative same-bar `SL` precedence.
- Grid-search foundation using a composite objective, minimum-trade gate, and R-based metrics.
- PostgreSQL schemas isolated from production: `raw`, `market`, `bt`, `analytics`, `config`.
- Every durable experiment is represented by `bt.run`, including scanner version, parameters, period, symbols, execution profile, seed, and git commit.

## Project layout

- `app/data`: historical clock, PostgreSQL/read-only repository adapter, 1m resampler.
- `app/scanners`: bridge to the `D:\py_pro\trad_bot` scanner modules.
- `app/backtest`: Level 1 signal/outcome engine. Portfolio simulation is intentionally a later level.
- `app/analytics`: expectancy, drawdown, Sharpe/Sortino, composite objective and walk-forward windows.
- `app/optimizer`: deterministic grid search.
- `app/db/schema.sql`: local PostgreSQL DDL.

## Local setup

```powershell
cd D:\py_pro\trad_bot_backtest
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

Create an independent local database named `trad_bot_backtest`, then apply `app/db/schema.sql`. Do **not** point this project at the production `trad_bot` database.

## Scanner integration

Use the installed/repository production code directly, not a forked copy:

```python
from app.scanners.adapters import add_production_project, ProductionScannerAdapter
add_production_project(r"D:\py_pro\trad_bot")
# Instantiate production ScannerOrchestrator/scanner and its compatible context builder.
# Then pass ProductionScannerAdapter(...).scan to SignalBacktest.
```

The integration context builder must fetch through `HistoricalDataProvider`; do not call exchange APIs or inject future candles. The existing `trad_bot/app/scanners/outcome.py` is the behavioral reference; this project has a dependency-free equivalent so research can run independently while compatibility tests are expanded.

## CLI contracts

```powershell
python -m scripts.run_backtest --scanner TREND_PULLBACK --direction LONG --from 2025-01-01 --to 2026-01-01 --symbols BTCUSDT ETHUSDT
python -m scripts.export_backtest --run-id 4572b486-41fd-4b64-8f75-a335996514a1 --run-id fc274d7c-6051-4f3b-82a6-c66b0c6e2537
python -m scripts.optimize_scanner --scanner TREND_PULLBACK --direction LONG --method grid --trials 100
```

`run_backtest` loads canonical 1m candles from PostgreSQL, deterministically resamples the closed 5m/15m/1h/4h bars, invokes the production `TrendPullbackScanner`, evaluates the next 48 1m bars, and persists `bt.run`, `bt.setup`, and `bt.outcome`.  Pass `--production-root` when the production repository is not at `../trad_bot`; database connection settings come from standard `PG*` environment variables.

`export_backtest` creates analysis files under `exports/`: a detailed CSV with one row per setup/outcome, a summary CSV grouped by `run × direction × symbol × regime × month`, and a small JSON manifest.  These files are intended for Excel, pandas, notebooks, or BI tools.

## Validation protocol

Optimize only on TRAIN, then keep configurations that remain positive on VALIDATION and TEST. Prefer walk-forward windows and stable parameter neighborhoods over peak historical PnL. Inspect results by `scanner × direction × regime × score bucket × symbol × month`; minimum trades are mandatory before an objective can rank a parameter set.

## Git handoff

Work is on `feat/historical-scanner-backtest`. Review locally, commit, then push with:

```powershell
git push -u origin feat/historical-scanner-backtest
```
