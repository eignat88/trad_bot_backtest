CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS market;
CREATE SCHEMA IF NOT EXISTS bt;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS config;
CREATE SCHEMA IF NOT EXISTS dds;
CREATE SCHEMA IF NOT EXISTS mart;

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

-- Research layer: all values in these snapshots are frozen at the signal timestamp.
-- Never update a feature snapshot with information from a later candle.
CREATE TABLE IF NOT EXISTS dds.market_context_snapshot (
    id UUID PRIMARY KEY, snapshot_time TIMESTAMPTZ NOT NULL,
    btc_return_15m NUMERIC, btc_return_1h NUMERIC, btc_return_4h NUMERIC, btc_return_24h NUMERIC,
    eth_return_1h NUMERIC, eth_return_4h NUMERIC,
    market_breadth_1h NUMERIC, market_breadth_4h NUMERIC,
    median_alt_return_1h NUMERIC, median_alt_return_4h NUMERIC,
    cross_sectional_volatility NUMERIC, btc_dominance NUMERIC,
    regime TEXT, regime_version TEXT NOT NULL,
    UNIQUE (snapshot_time, regime_version)
);

CREATE TABLE IF NOT EXISTS dds.setup_feature_snapshot (
    setup_id UUID PRIMARY KEY REFERENCES bt.setup(id),
    instrument_id BIGINT REFERENCES market.instrument(id), market_context_id UUID REFERENCES dds.market_context_snapshot(id),
    scanner_version TEXT, feature_set_version TEXT NOT NULL, signal_time TIMESTAMPTZ NOT NULL,
    -- trend / momentum
    ema20_distance_pct NUMERIC, ema50_distance_pct NUMERIC, ema200_distance_pct NUMERIC,
    ema20_slope NUMERIC, ema50_slope NUMERIC, adx NUMERIC, trend_strength NUMERIC,
    rsi_14 NUMERIC, rsi_delta_3 NUMERIC, macd_hist NUMERIC, macd_hist_delta NUMERIC, roc_5 NUMERIC, roc_20 NUMERIC,
    -- volatility / liquidity / structure
    atr_pct NUMERIC, atr_percentile_30d NUMERIC, bb_width NUMERIC, bb_width_percentile NUMERIC, realized_volatility NUMERIC,
    volume_ratio_20 NUMERIC, volume_zscore NUMERIC, quote_volume NUMERIC, spread_bps NUMERIC, orderbook_imbalance NUMERIC, liquidity_score NUMERIC,
    body_pct NUMERIC, upper_wick_pct NUMERIC, lower_wick_pct NUMERIC, distance_to_support_atr NUMERIC, distance_to_resistance_atr NUMERIC, range_position NUMERIC,
    -- cross-sectional and scanner-specific values
    symbol_return_rank_1h NUMERIC, symbol_return_rank_4h NUMERIC, volume_rank NUMERIC, volatility_rank NUMERIC,
    relative_strength_btc NUMERIC, relative_strength_market NUMERIC,
    scanner_score NUMERIC, risk_distance_atr NUMERIC, target_distance_atr NUMERIC, rr_planned NUMERIC, confirmation_count INTEGER,
    hour_of_day SMALLINT, day_of_week SMALLINT, features JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_feature_snapshot_dims ON dds.setup_feature_snapshot (scanner_version, signal_time);
CREATE INDEX IF NOT EXISTS ix_feature_snapshot_context ON dds.setup_feature_snapshot (market_context_id);

CREATE TABLE IF NOT EXISTS dds.setup_confluence (
    setup_id UUID NOT NULL REFERENCES bt.setup(id), other_setup_id UUID NOT NULL REFERENCES bt.setup(id),
    other_scanner TEXT NOT NULL, same_direction BOOLEAN NOT NULL, time_delta_sec INTEGER NOT NULL, price_distance_pct NUMERIC,
    PRIMARY KEY (setup_id, other_setup_id), CHECK (setup_id <> other_setup_id)
);
CREATE INDEX IF NOT EXISTS ix_confluence_lookup ON dds.setup_confluence (setup_id, same_direction);

-- Independent signal edge: market movement after the signal, regardless of execution gates.
CREATE TABLE IF NOT EXISTS dds.signal_outcome (
    setup_id UUID PRIMARY KEY REFERENCES bt.setup(id), evaluated_at TIMESTAMPTZ NOT NULL,
    return_5m NUMERIC, return_15m NUMERIC, return_30m NUMERIC, return_1h NUMERIC, return_4h NUMERIC, return_12h NUMERIC, return_24h NUMERIC,
    mfe_15m_r NUMERIC, mfe_1h_r NUMERIC, mfe_4h_r NUMERIC, mfe_24h_r NUMERIC,
    mae_15m_r NUMERIC, mae_1h_r NUMERIC, mae_4h_r NUMERIC, mae_24h_r NUMERIC,
    hit_05r BOOLEAN, hit_10r BOOLEAN, hit_15r BOOLEAN, hit_20r BOOLEAN, hit_stop_before_1r BOOLEAN,
    time_to_05r_min INTEGER, time_to_1r_min INTEGER, time_to_stop_min INTEGER,
    CHECK ((mfe_15m_r IS NULL OR mfe_15m_r >= 0) AND (mfe_1h_r IS NULL OR mfe_1h_r >= 0)
       AND (mfe_4h_r IS NULL OR mfe_4h_r >= 0) AND (mfe_24h_r IS NULL OR mfe_24h_r >= 0)),
    CHECK ((mae_15m_r IS NULL OR mae_15m_r <= 0) AND (mae_1h_r IS NULL OR mae_1h_r <= 0)
       AND (mae_4h_r IS NULL OR mae_4h_r <= 0) AND (mae_24h_r IS NULL OR mae_24h_r <= 0))
);

CREATE OR REPLACE VIEW mart.edge_dataset AS
SELECT s.id AS setup_id, s.scanner_name, f.scanner_version, s.symbol, s.direction, s.detected_at AS signal_time,
       s.regime AS setup_regime, s.score, f.feature_set_version,
       f.ema20_distance_pct, f.ema50_distance_pct, f.ema200_distance_pct, f.ema20_slope, f.ema50_slope, f.adx, f.trend_strength,
       f.rsi_14, f.rsi_delta_3, f.macd_hist, f.macd_hist_delta, f.roc_5, f.roc_20,
       f.atr_pct, f.atr_percentile_30d, f.bb_width, f.bb_width_percentile, f.realized_volatility,
       f.volume_ratio_20, f.volume_zscore, f.quote_volume, f.spread_bps, f.orderbook_imbalance, f.liquidity_score,
       f.body_pct, f.upper_wick_pct, f.lower_wick_pct, f.distance_to_support_atr, f.distance_to_resistance_atr, f.range_position,
       f.symbol_return_rank_1h, f.symbol_return_rank_4h, f.volume_rank, f.volatility_rank, f.relative_strength_btc, f.relative_strength_market,
       f.scanner_score, f.risk_distance_atr, f.target_distance_atr, f.rr_planned, f.confirmation_count, f.hour_of_day, f.day_of_week,
       f.features AS feature_payload, m.regime AS market_regime, m.btc_return_1h, m.btc_return_4h, m.market_breadth_1h,
       o.return_1h, o.return_4h, o.return_24h, o.mfe_1h_r, o.mfe_4h_r, o.mfe_24h_r, o.mae_1h_r, o.mae_4h_r, o.mae_24h_r,
       o.hit_10r, o.hit_stop_before_1r, b.result_r, b.mfe_r, b.mae_r, b.fee_slippage_adjusted_result_r
FROM bt.setup s
LEFT JOIN dds.setup_feature_snapshot f ON f.setup_id = s.id
LEFT JOIN dds.market_context_snapshot m ON m.id = f.market_context_id
LEFT JOIN dds.signal_outcome o ON o.setup_id = s.id
LEFT JOIN bt.outcome b ON b.setup_id = s.id;
