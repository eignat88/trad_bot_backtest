# Спецификация: Edge-Aware Signal Filter Pipeline

## Контекст

На основании анализа 134,030 сетапов с фичами и ~350K сделок из `bt.outcome` выявлено, что текущий trading bot (`trad-bot-paper`) пропускает сигналы без учёта статистического edge. Все 3 сканера в убытке после учёта fees/slippage:

| Сканер | Win Rate | Avg Adj R |
|---|---|---|
| MOMENTUM_EXHAUSTION | 31-34% | -0.237 |
| LIQUIDITY_REVERSAL | 31-32% | -0.044 to -0.071 |
| TREND_PULLBACK | 17-29% | -0.040 to -0.280 |

Найдены конкретные комбинации фичей с положительным expectancy.

---

## Цель

Построить промежуточный слой (filter pipeline) между scanner и paper engine, который:
1. Получает raw signal от scanner
2. Вычисляет feature-based score
3. Фильтрует по найденным порогам
4. Считает expectancy с учётом fees
5. Пропускает только setups с positive expectancy

---

## Найденные Edge-Правила

### Rule 1: ETHUSDT LIQUIDITY_REVERSAL LONG

**Лучший edge в базе.**

| Параметр | Порог | Win Rate | Avg R |
|---|---|---|---|
| RSI 14 | < 50 | 54.4% | +0.553 |
| ADX | < 25 | 54.4% | +0.553 |
| Volume Ratio 20 | < 1.5 | 54.4% | +0.553 |

**Строгий фильтр (ADXR<25 + RSI<50):** 55% win rate, +0.4R avg
**Мягкий фильтр (ADXR<25 + RSI 50-60):** 45.6% win rate, +0.22R avg

**Минимальный порог:** expectancy > 0 после fees при R:R = configured

### Rule 2: LIQUIDITY_REVERSAL SHORT (любой символ)

| Параметр | Порог | Win Rate | Avg R |
|---|---|---|---|
| distance_to_resistance_atr | 0.5 - 1.0 | 48.7% | +0.456 |
| ADX | < 10 | 35.9% | +0.017 |
| Volume Ratio 20 | 1.5 - 2.0 | 37.5% | +0.007 |

**Лучший комбо:** distance_to_resistance 0.5-1.0 ATR → 48.7% WR, +0.456R

### Rule 3: MOMENTUM_EXHAUSTION — SKIP ALL

Все комбинации убыточны. Фильтр должен **полностью блокировать** этот сканер.

### Rule 4: TREND_PULLBACK SHORT — SKIP ALL

16.9% win rate. Полностью блокировать.

---

## Архитектура

```
scanner_runner.py
       │
       ▼
┌─────────────────────┐
│  signal_outpost.py   │  ← НОВЫЙ МОДУЛЬ
│  (Filter Pipeline)   │
│                     │
│  1. receive signal   │
│  2. fetch features   │
│  3. apply rules      │
│  4. calc expectancy  │
│  5. pass/reject      │
└─────────┬───────────┘
          │
          ▼
   paper_engine.py
   (только approved signals)
```

---

## Модули

### 1. `app/filter/edge_rules.py` — Правила фильтрации

Определяет edge-правила как данные:

```python
EdgeRule = dict {
    "rule_id": str,
    "scanner_name": str,
    "direction": str,
    "symbol": str | None,         # None = все символы
    "filters": list[FilterCondition],
    "min_expectancy_r": float,     # минимальный expectancy в R
    "enabled": bool,
}

FilterCondition = dict {
    "feature": str,               # название колонки из setup_feature_snapshot
    "operator": str,              # "lt", "gt", "between"
    "value": float | tuple,       # пороговое значение
}
```

**Правила по умолчанию:**

| rule_id | scanner | direction | symbol | filters | min_exp |
|---|---|---|---|---|---|
| `eth_lr_long_strict` | LIQUIDITY_REVERSAL | LONG | ETHUSDT | RSI<50, ADX<25, vol<1.5 | +0.3R |
| `eth_lr_long_moderate` | LIQUIDITY_REVERSAL | LONG | ETHUSDT | RSI<60, ADX<25 | +0.1R |
| `lr_short_near_resistance` | LIQUIDITY_REVERSAL | SHORT | * | dist_to_res 0.5-1.0, ADX<10 | +0.1R |
| `lr_short_moderate` | LIQUIDITY_REVERSAL | SHORT | * | ADX<25, vol 1.5-2.0 | 0R |
| `skip_momentum_exhaustion` | MOMENTUM_EXHAUSTION | * | * | BLOCK ALL | — |
| `skip_trend_pullback_short` | TREND_PULLBACK | SHORT | * | BLOCK ALL | — |

### 2. `app/filter/expectancy.py` — Расчёт Expectancy

```python
def calc_expectancy(
    win_rate: float,          # из исторических данных для matching combos
    avg_win_r: float,         # средний выигрыш в R
    avg_loss_r: float,        # средний проигрыш в R (обычно -1R)
    fee_per_trade_r: float,   # fees в R (0.01-0.03典型)
    slippage_r: float,        # slippage в R (0.005-0.01)
) -> float:
    """Expectancy = WR * avg_win - (1-WR) * (avg_loss + fees + slippage)"""
    gross = win_rate * avg_win_r - (1 - win_rate) * abs(avg_loss_r)
    net = gross - fee_per_trade_r - slippage_r
    return net
```

**Калибровка fees:**
- Binance taker fee: 0.04% → 0.04R при 1R target
- Slippage оценка: ~0.01R на market order
- Итого: ~0.05R per trade round-trip

### 3. `app/filter/signal_filter.py` — Основной pipeline

```python
class SignalFilter:
    def __init__(self, db_session, rules: list[EdgeRule]):
        self.db = db_session
        self.rules = rules

    def evaluate(self, signal: dict) -> FilterResult:
        """
        signal = {
            "setup_id": uuid,
            "scanner_name": str,
            "direction": str,
            "symbol": str,
            "score": float,
        }
        returns FilterResult(approved bool, rule_id, expectancy_r, reason)
        """
        # 1. Fetch features from setup_feature_snapshot
        features = self._fetch_features(signal["setup_id"])

        # 2. Find matching rules
        matching_rules = self._match_rules(signal, features)

        # 3. For each matching rule, calc expectancy
        for rule in matching_rules:
            expectancy = self._calc_rule_expectancy(rule, features)
            if expectancy >= rule["min_expectancy_r"]:
                return FilterResult(
                    approved=True,
                    rule_id=rule["rule_id"],
                    expectancy_r=expectancy,
                    reason="edge_found"
                )

        # 4. No rule matched or all below threshold
        return FilterResult(
            approved=False,
            rule_id=None,
            expectancy_r=0,
            reason="no_edge"
        )
```

### 4. `app/filter/feature_store.py` — Получение фичей

```python
def fetch_features(db_session, setup_id: uuid) -> dict:
    """Fetch from dds.setup_feature_snapshot"""
    # SELECT * FROM dds.setup_feature_snapshot WHERE setup_id = :id
    # Returns dict of all 50 features
```

**Кэширование:** Features статичны после backfill, можно кэшировать в Redis/memory.

---

## Конфигурация

### `config/filter_config.yaml`

```yaml
filter_pipeline:
  enabled: true
  mode: "paper"  # "paper" | "live" (в paper — логирует, в live — блокирует)

  fees:
    taker_fee_pct: 0.04
    slippage_r: 0.01

  rules:
    - id: eth_lr_long_strict
      scanner: LIQUIDITY_REVERSAL
      direction: LONG
      symbol: ETHUSDT
      conditions:
        - feature: rsi_14
          op: lt
          value: 50
        - feature: adx
          op: lt
          value: 25
        - feature: volume_ratio_20
          op: lt
          value: 1.5
      min_expectancy_r: 0.3

    - id: lr_short_near_resistance
      scanner: LIQUIDITY_REVERSAL
      direction: SHORT
      symbol: "*"
      conditions:
        - feature: distance_to_resistance_atr
          op: between
          value: [0.5, 1.0]
      min_expectancy_r: 0.1

    - id: skip_momentum_exhaustion
      scanner: MOMENTUM_EXHAUSTION
      direction: "*"
      symbol: "*"
      action: block

    - id: skip_trend_pullback_short
      scanner: TREND_PULLBACK
      direction: SHORT
      symbol: "*"
      action: block
```

---

## Интеграция с paper_runner.py

### Текущий flow:
```python
# paper_runner.py
for signal in scanner.get_signals():
    # Прямой пропуск в engine
    engine.process_signal(signal)
```

### Новый flow:
```python
# paper_runner.py
from app.filter.signal_filter import SignalFilter

signal_filter = SignalFilter(db, load_rules())

for signal in scanner.get_signals():
    result = signal_filter.evaluate(signal)
    if result.approved:
        engine.process_signal(signal)
        log.info(f"signal approved: {signal.symbol} {signal.direction} "
                 f"rule={result.rule_id} expectancy={result.expectancy_r:.3f}R")
    else:
        log.debug(f"signal rejected: {signal.symbol} {signal.direction} "
                  f"reason={result.reason}")
```

---

## Метрики для мониторинга

### В Grafana / logs:

| Метрика | Описание |
|---|---|
| `filter_signals_received` | Сколько сигналов получено |
| `filter_signals_approved` | Сколько прошло фильтр |
| `filter_signals_rejected` | Сколько отклонено |
| `filter_approval_rate` | % прошедших |
| `filter_avg_expectancy` | Средний expectancy прошедших |
| `filter_edge_hit_rate` | % approved с positive expectancy в реальности |

### SQL для проверки:

```sql
-- За последние 24ч: сколько сигналов approved/rejected
SELECT
  DATE_TRUNC('hour', s.detected_at) as hour,
  s.scanner_name,
  COUNT(*) as total,
  SUM(CASE WHEN f_outcome = 'approved' THEN 1 ELSE 0 END) as approved
FROM bt.setup s
-- JOIN с логами фильтра (новая таблица)
GROUP BY 1, 2 ORDER BY 1;
```

---

## Новая таблица: `filter_log`

```sql
CREATE TABLE IF NOT EXISTS filter.log (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    setup_id        uuid NOT NULL REFERENCES bt.setup(id),
    detected_at     timestamptz NOT NULL,
    scanner_name    text NOT NULL,
    symbol          text NOT NULL,
    direction       text NOT NULL,
    rule_id         text,
    approved        boolean NOT NULL,
    expectancy_r    numeric,
    reject_reason   text,
    features_snapshot jsonb,
    created_at      timestamptz DEFAULT now()
);

CREATE INDEX idx_filter_log_detected ON filter.log (detected_at DESC);
CREATE INDEX idx_filter_log_approved ON filter.log (approved) WHERE approved = true;
```

---

## Тесты

### Unit tests:

| Тест | Описание |
|---|---|
| `test_eth_lr_long_strict_match` | RSI=45, ADX=20 → approved |
| `test_eth_lr_long_strict_reject_high_rsi` | RSI=65 → rejected |
| `test_lr_short_near_resistance_match` | dist=0.7 ATR → approved |
| `test_lr_short_near_resistance_reject_close` | dist=0.2 ATR → rejected |
| `test_skip_momentum_exhaustion` | ME signal → always rejected |
| `test_expectancy_calculation` | WR=0.55, avg_win=0.5R, fees=0.05R → +0.2R |
| `test_fee_impact` | Same setup with 0.1R fees → -0.05R |

### Integration test:

```python
# Симуляция 1000 сигналов из БД, проверка что фильтр пропускает только profitable
def test_filter_end_to_end():
    signals = db.query("SELECT * FROM bt.setup WHERE ... LIMIT 1000")
    results = [filter.evaluate(s) for s in signals]
    approved = [r for r in results if r.approved]

    # Все approved должны иметь expectancy > 0
    assert all(r.expectancy_r > 0 for r in approved)

    # Approval rate должен быть < 30% (строгий фильтр)
    assert len(approved) / len(results) < 0.30
```

---

## Delivery Plan

| Фаза | Описание | Срок |
|---|---|---|
| **Phase 1** | `edge_rules.py` + `expectancy.py` + unit tests | 1 день |
| **Phase 2** | `signal_filter.py` + `feature_store.py` + integration test | 1 день |
| **Phase 3** | `filter_log` table + интеграция с paper_runner | 0.5 дня |
| **Phase 4** | Grafana dashboard фильтра | 0.5 дня |
| **Phase 5** | Backtest фильтра на исторических данных (валидация) | 1 день |

**Итого:** ~4 дня разработки

---

## Валидация (Phase 5)

Перед включением в live/paper必须要:

1. Запустить фильтр на **historical signals** (все 134K setups)
2. Посчитать expectancy **только для approved**
3. Сравнить с expectancy **без фильтра**
4. Убедиться что approval rate < 30% и avg expectancy > 0

```sql
-- Валидация: hypothetical P&L approved vs all
SELECT
  'without_filter' as mode,
  COUNT(*) as trades,
  ROUND(AVG(o.fee_slippage_adjusted_result_r), 3) as avg_r,
  ROUND(SUM(o.fee_slippage_adjusted_result_r), 2) as total_r
FROM bt.setup s
JOIN bt.outcome o ON o.setup_id = s.id

UNION ALL

SELECT
  'with_filter' as mode,
  COUNT(*) as trades,
  ROUND(AVG(o.fee_slippage_adjusted_result_r), 3) as avg_r,
  ROUND(SUM(o.fee_slippage_adjusted_result_r), 2) as total_r
FROM bt.setup s
JOIN bt.outcome o ON o.setup_id = s.id
JOIN dds.setup_feature_snapshot f ON f.setup_id = s.id
WHERE (
  -- ETH LR LONG strict
  (s.symbol = 'ETHUSDT' AND s.scanner_name = 'LIQUIDITY_REVERSAL'
   AND s.direction = 'LONG' AND f.rsi_14 < 50 AND f.adx < 25 AND f.volume_ratio_20 < 1.5)
  OR
  -- LR SHORT near resistance
  (s.scanner_name = 'LIQUIDITY_REVERSAL' AND s.direction = 'SHORT'
   AND f.distance_to_resistance_atr BETWEEN 0.5 AND 1.0)
)
AND s.scanner_name != 'MOMENTUM_EXHAUSTION'
AND NOT (s.scanner_name = 'TREND_PULLBACK' AND s.direction = 'SHORT');
```

---

## Файлы для создания

| Файл | Описание |
|---|---|
| `app/filter/__init__.py` | Package |
| `app/filter/edge_rules.py` | Edge rules data + loader |
| `app/filter/expectancy.py` | Expectancy calculator |
| `app/filter/signal_filter.py` | Main pipeline |
| `app/filter/feature_store.py` | Feature fetcher with cache |
| `app/db/migrations/003_filter_log.sql` | filter.log table |
| `config/filter_config.yaml` | Configuration |
| `tests/test_filter/test_edge_rules.py` | Rule tests |
| `tests/test_filter/test_expectancy.py` | Expectancy tests |
| `tests/test_filter/test_signal_filter.py` | Integration tests |
