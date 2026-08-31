CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS bt;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS config;

CREATE TABLE IF NOT EXISTS market.instrument (
    id BIGSERIAL PRIMARY KEY, symbol TEXT NOT NULL UNIQUE, exchange TEXT NOT NULL DEFAULT 'bybit', active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS market.candle (
    instrument_id BIGINT NOT NULL REFERENCES market.instrument(id), timeframe TEXT NOT NULL, open_time TIMESTAMPTZ NOT NULL,
    open NUMERIC NOT NULL, high NUMERIC NOT NULL, low NUMERIC NOT NULL, close NUMERIC NOT NULL, volume NUMERIC NOT NULL, turnover NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (instrument_id, timeframe, open_time)
);
CREATE TABLE IF NOT EXISTS config.parameter_set (
    id BIGSERIAL PRIMARY KEY, scanner_name TEXT NOT NULL, parameters JSONB NOT NULL, parameter_hash TEXT NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bt.run (
    id UUID PRIMARY KEY, scanner_version TEXT NOT NULL, parameter_set_id BIGINT REFERENCES config.parameter_set(id), execution_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_at TIMESTAMPTZ NOT NULL, end_at TIMESTAMPTZ NOT NULL, symbols JSONB NOT NULL, initial_balance NUMERIC, random_seed INTEGER, git_commit TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bt.setup (
    id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES bt.run(id), scanner_name TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, regime TEXT, score NUMERIC, detected_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS bt.outcome (
    setup_id UUID PRIMARY KEY REFERENCES bt.setup(id), entry_touched BOOLEAN NOT NULL, first_event TEXT NOT NULL, result_r NUMERIC NOT NULL, mfe_r NUMERIC NOT NULL, mae_r NUMERIC NOT NULL, bars_to_entry INTEGER, bars_to_exit INTEGER, fee_slippage_adjusted_result_r NUMERIC NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_candle_lookup ON market.candle (timeframe, open_time);
CREATE INDEX IF NOT EXISTS ix_setup_dimensions ON bt.setup (run_id, scanner_name, direction, regime);
