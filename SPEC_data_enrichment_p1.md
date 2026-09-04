# Спецификация: Data Enrichment — Priority 1

## Контекст

Backtest база содержит 13 инструментов, 6M свечей (1m), 331K сетапов и 50 фич. Для полноценного поиска edge не хватает трёх категорий данных: funding rate, multi-timeframe свечи, sector-классификация.

---

## 1. Funding Rate

### Источник

Binance Futures API — `GET /fapi/v1/fundingRate`

**Бесплатно**, не требует API key для исторических данных.

### Характеристики

| Параметр | Значение |
|---|---|
| Интервал | 8 часов (00:00, 08:00, 16:00 UTC) |
| Хранить | symbol, funding_time, funding_rate |
| Диапазон | Сколько есть (Binance хранит ~2 года) |
| Объём | 13 символов × 3 в день × 365 = ~14K записей/год |

### Схема

```sql
CREATE TABLE IF NOT EXISTS market.funding_rate (
    instrument_id   bigint NOT NULL REFERENCES market.instrument(id),
    funding_time    timestamp with time zone NOT NULL,
    funding_rate    numeric NOT NULL,    -- например 0.0001 = 0.01%
    PRIMARY KEY (instrument_id, funding_time)
);

CREATE INDEX idx_funding_rate_time ON market.funding_rate (funding_time DESC);
```

### Скрипт загрузки

```python
# scripts/download_funding_rate.py
#
# Usage:
#   .venv/bin/python scripts/download_funding_rate.py [--start 2025-01-01] [--end 2025-12-31]
#
# Логика:
#   1. Для каждого instrument_id из market.instrument
#   2. GET https://fapi.binance.com/fapi/v1/fundingRate?symbol={SYMBOL}&startTime={MS}&limit=1000
#   3. Пагинация: следующий startTime = last.funding_time + 1ms
#   4. INSERT INTO market.funding_rate (instrument_id, funding_time, funding_rate)
#      ON CONFLICT (instrument_id, funding_time) DO NOTHING
#   5. Лог: [BTCUSDT] fetched 1000 rows, total=1095
```

### API Limitations

- Rate limit: 10 запросов/секунду
- Limit max: 1000 за запрос
- Пагинация обязательна

### Ожидаемый результат

~14K записей за 2025 год на все 13 символов.

---

## 2. Multi-Timeframe Candles

### Источник

Binance API — `GET /fapi/v1/klines` (Futures) или `/api/v3/klines` (Spot)

### Характеристики

| Параметр | Значение |
|---|---|
| Timeframes | **15m**, **1h** (добавить к существующим 1m) |
| Диапазон | Тот же что 1m: 2025-01-01 — 2025-12-31 |
| Объём на символ | 15m: ~35K свечей/год, 1h: ~8.7K свечей/год |
| Итого | 13 × (35K + 8.7K) = ~570K новых записей |

### Схема

Та же таблица `market.candle`, добавляется `timeframe = '15m'` и `timeframe = '1h'`.

```sql
-- Таблица уже существует, просто добавляем данные с новыми timeframe.
-- Уникальный constraint: (instrument_id, timeframe, open_time)
-- Проверить и добавить если нет:
ALTER TABLE market.candle
    ADD CONSTRAINT uq_candle_instr_tf_time
    UNIQUE (instrument_id, timeframe, open_time);
```

### Скрипт загрузки

```python
# scripts/download_candles.py
#
# Usage:
#   .venv/bin/python scripts/download_candles.py --timeframes 15m 1h [--start 2025-01-01] [--end 2025-12-31]
#
# Логика:
#   1. Для каждого timeframe в [15m, 1h]
#   2. Для каждого instrument_id из market.instrument
#   3. GET https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL}&interval={TF}&startTime={MS}&limit=1500
#   4. Пагинация: следующий startTime = last.open_time + 1ms
#   5. INSERT INTO market.candle (instrument_id, timeframe, open_time, open, high, low, close, volume, turnover)
#      ON CONFLICT (instrument_id, timeframe, open_time) DO NOTHING
#   6. Лог: [BTCUSDT 15m] fetched 1500 rows, total=35040
```

### API Limitations

- Rate limit: 1200 запросов/мин (权重 1-5)
- Limit max: 1500 за klines
- Вес: 1m=1, 3m=2, 5m=2, 15m=2, 30m=5, 1h=5, ...

### Ожидаемый результат

~570K новых записей в `market.candle` с timeframe 15m и 1h.

---

## 3. Sector Classification

### Источник

Ручная классификация. Таблица-справочник.

### Схема

```sql
CREATE TABLE IF NOT EXISTS market.sector (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    description text
);

CREATE TABLE IF NOT EXISTS market.instrument_sector (
    instrument_id   bigint NOT NULL REFERENCES market.instrument(id),
    sector_id       int NOT NULL REFERENCES market.sector(id),
    PRIMARY KEY (instrument_id, sector_id)
);

-- Seed data
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
```

### Файл

```sql
-- scripts/apply_sectors.sql
-- Выполнить один раз:
--   psql -U postgres -h localhost -p 5432 -d trad_bot_backtest -f scripts/apply_sectors.sql
```

---

## Файлы для создания

| Файл | Описание |
|---|---|
| `scripts/download_funding_rate.py` | Загрузка funding rate из Binance API |
| `scripts/download_candles.py` | Загрузка 15m/1h свечей из Binance API |
| `scripts/apply_sectors.sql` | SQL для создания sector-таблиц и seed data |
| `app/db/migrations/004_funding_rate.sql` | DDL для market.funding_rate |
| `app/db/migrations/005_candle_unique.sql` | Unique constraint для candle |
| `app/db/migrations/006_sectors.sql` | DDL для sector/instrument_sector |

---

## Delivery Plan

| Фаза | Описание | Срок |
|---|---|---|
| **Phase 1** | Sector tables + seed data + SQL | 0.5 дня |
| **Phase 2** | download_funding_rate.py + миграция | 1 день |
| **Phase 3** | download_candles.py (15m, 1h) | 1 день |
| **Phase 4** | Проверка данных + обновление edge_dataset view | 0.5 дня |

**Итого:** ~3 дня

---

## Проверка после загрузки

```sql
-- 1. Funding rate: сколько записей
SELECT i.symbol, COUNT(*) as rows,
       MIN(f.funding_time) as first, MAX(f.funding_time) as last
FROM market.funding_rate f
JOIN market.instrument i ON i.id = f.instrument_id
GROUP BY i.symbol ORDER BY i.symbol;

-- 2. Candles: количество по timeframe
SELECT timeframe, COUNT(*) as rows,
       COUNT(DISTINCT instrument_id) as instruments
FROM market.candle
GROUP BY timeframe ORDER BY timeframe;

-- 3. Sectors: все ли инструменты классифицированы
SELECT i.symbol, s.name as sector
FROM market.instrument i
LEFT JOIN market.instrument_sector ist ON ist.instrument_id = i.id
LEFT JOIN market.sector s ON s.id = ist.sector_id
ORDER BY i.symbol;
```
