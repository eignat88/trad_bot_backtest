-- Migration 004: Funding Rate table
-- Binance Futures API funding rate data (8-hour intervals)

CREATE TABLE IF NOT EXISTS market.funding_rate (
    instrument_id   bigint NOT NULL REFERENCES market.instrument(id),
    funding_time    timestamp with time zone NOT NULL,
    funding_rate    numeric NOT NULL,    -- e.g. 0.0001 = 0.01%
    PRIMARY KEY (instrument_id, funding_time)
);

CREATE INDEX IF NOT EXISTS idx_funding_rate_time ON market.funding_rate (funding_time DESC);
CREATE INDEX IF NOT EXISTS idx_funding_rate_instrument ON market.funding_rate (instrument_id);
