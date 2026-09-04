-- scripts/apply_sectors.sql
-- Standalone SQL to create sector tables and seed data
-- Usage:
--   psql -U postgres -h localhost -p 5432 -d trad_bot_backtest -f scripts/apply_sectors.sql

-- Create sector table
CREATE TABLE IF NOT EXISTS market.sector (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    description text
);

-- Create instrument_sector mapping table
CREATE TABLE IF NOT EXISTS market.instrument_sector (
    instrument_id   bigint NOT NULL REFERENCES market.instrument(id),
    sector_id       int NOT NULL REFERENCES market.sector(id),
    PRIMARY KEY (instrument_id, sector_id)
);

-- Seed sectors
INSERT INTO market.sector (name, description) VALUES
    ('L1',       'Layer 1 блокчейны'),
    ('L2',       'Layer 2 решения'),
    ('DeFi',     'Децентрализованные финансы'),
    ('Meme',     'Мемкоины'),
    ('AI',       'AI/Data проекты'),
    ('RWA',      'Real World Assets'),
    ('Exchange', 'Токены бирж'),
    ('Infra',    'Инфраструктурные проекты')
ON CONFLICT (name) DO NOTHING;

-- Seed instrument-sector mappings
INSERT INTO market.instrument_sector (instrument_id, sector_id) VALUES
    ((SELECT id FROM market.instrument WHERE symbol='BTCUSDT'),      (SELECT id FROM market.sector WHERE name='L1')),
    ((SELECT id FROM market.instrument WHERE symbol='ETHUSDT'),      (SELECT id FROM market.sector WHERE name='L1')),
    ((SELECT id FROM market.instrument WHERE symbol='SOLUSDT'),      (SELECT id FROM market.sector WHERE name='L1')),
    ((SELECT id FROM market.instrument WHERE symbol='BNBUSDT'),      (SELECT id FROM market.sector WHERE name='Exchange')),
    ((SELECT id FROM market.instrument WHERE symbol='XRPUSDT'),      (SELECT id FROM market.sector WHERE name='L1')),
    ((SELECT id FROM market.instrument WHERE symbol='DOGEUSDT'),     (SELECT id FROM market.sector WHERE name='Meme')),
    ((SELECT id FROM market.instrument WHERE symbol='1000PEPEUSDT'), (SELECT id FROM market.sector WHERE name='Meme')),
    ((SELECT id FROM market.instrument WHERE symbol='ADAUSDT'),      (SELECT id FROM market.sector WHERE name='L1')),
    ((SELECT id FROM market.instrument WHERE symbol='NEARUSDT'),     (SELECT id FROM market.sector WHERE name='L1')),
    ((SELECT id FROM market.instrument WHERE symbol='ONDOUSDT'),     (SELECT id FROM market.sector WHERE name='RWA')),
    ((SELECT id FROM market.instrument WHERE symbol='HYPEUSDT'),     (SELECT id FROM market.sector WHERE name='DeFi')),
    ((SELECT id FROM market.instrument WHERE symbol='SUIUSDT'),      (SELECT id FROM market.sector WHERE name='L1')),
    ((SELECT id FROM market.instrument WHERE symbol='AVAXUSDT'),     (SELECT id FROM market.sector WHERE name='L1'))
ON CONFLICT DO NOTHING;
