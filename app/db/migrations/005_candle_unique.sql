-- Migration 005: Unique constraint for candle table
-- Ensures (instrument_id, timeframe, open_time) is unique
-- This constraint already exists as PRIMARY KEY, but we verify it exists
-- for multi-timeframe support (1m, 15m, 1h, etc.)

DO $$
BEGIN
    -- Check if the unique constraint already exists (it should as PK)
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'candle_pkey'
        AND conrelid = 'market.candle'::regclass
    ) THEN
        ALTER TABLE market.candle
            ADD CONSTRAINT uq_candle_instr_tf_time
            UNIQUE (instrument_id, timeframe, open_time);
    END IF;
END
$$;
