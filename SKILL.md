# Crypto Scanner Backtest & Optimization Skill

## Назначение

Этот skill используется для исследования, тестирования и оптимизации криптовалютных сканеров.

В системе существуют два отдельных проекта:

1. **`trad_bot`** (`D:\py_pro\trad_bot`)
   - основной production-проект;
   - содержит реальные реализации сканеров;
   - используется для поиска торговых сигналов и paper/live торговли;
   - является источником истины по логике сканеров.

2. **`trad_bot_backtest`** (`D:\py_pro\trad_bot_backtest`)
   - исследовательский проект;
   - использует исторические OHLCV-данные;
   - запускает production-логику сканеров на истории;
   - сравнивает работу сканеров на разных монетах, таймфреймах и настройках;
   - сохраняет результаты прогонов;
   - используется для поиска более эффективных параметров сканеров.

Главная задача агента — не просто запускать backtest, а системно исследовать поведение сканеров и находить параметры, которые потенциально улучшают качество торговых сигналов.

---

# Основной принцип

Production-код сканера является источником истины.

Нельзя создавать в backtest-проекте упрощённую копию торговой логики, если можно использовать production-реализацию сканера.

При анализе всегда необходимо отличать:

- изменение параметров сканера;
- изменение самой торговой логики;
- изменение условий тестирования;
- изменение исторических данных;
- изменение логики оценки результата сделки.

Нельзя смешивать эти изменения в одном эксперименте без явного указания.

---

# Рабочие каталоги

Основной проект: `D:\py_pro\trad_bot`

Проект исторического тестирования: `D:\py_pro\trad_bot_backtest`

Перед выполнением операций необходимо определить, в каком проекте должна выполняться конкретная задача.

---

# Что должен уметь агент

## 1. Анализировать production-сканер

Перед оптимизацией конкретного сканера агент должен определить:

- файл реализации сканера;
- класс или функцию сканера;
- доступные параметры;
- значения параметров по умолчанию;
- поддерживаемые направления LONG/SHORT;
- основной signal timeframe;
- используемые higher timeframes;
- необходимые индикаторы;
- фильтры;
- правила формирования setup;
- Stop Loss;
- Take Profit;
- target R;
- score;
- причины принятия сигнала;
- причины отклонения кандидата.

**Не менять production-код на этом этапе.**

---

# 2. Проверять соответствие backtest production-коду

Перед крупным исследованием проверить, что `trad_bot_backtest` действительно использует актуальную production-логику сканера.

Проверить:

- импорт production scanner (`app.scanners.adapters.ProductionScannerAdapter`);
- соответствие параметров;
- направление LONG/SHORT;
- формирование features;
- расчёт entry;
- stop;
- target;
- score;
- resampling таймфреймов (`app.data.resampler`);
- отсутствие дублирующей старой реализации сканера.

Если backtest расходится с production-кодом, сначала зафиксировать это как проблему.

**Не делать вывод об эффективности сканера по некорректному backtest.**

---

# 3. Проверять исторические данные

Перед тестированием проверить наличие OHLCV в PostgreSQL базе `trad_bot_backtest`.

Для каждой комбинации `symbol × timeframe × date range` необходимо определить:

- существует ли инструмент;
- первая доступная свеча;
- последняя доступная свеча;
- количество свечей;
- наличие больших пропусков;
- базовый timeframe данных (1m);
- возможность построить необходимые higher timeframes через resample (5m, 15m, 1h, 4h).

**Не запускать большой эксперимент на неполных данных без предупреждения.**

---

# 4. Создавать эксперимент

Каждый эксперимент должен иметь конкретную гипотезу.

Плохой вариант:
> "Попробовать разные настройки TREND_PULLBACK."

Хороший вариант:
> "Проверить, уменьшает ли max_pullback_quality с 0.75 до 0.60 количество слабых LONG-сигналов TREND_PULLBACK и повышает ли expectancy без критического уменьшения количества сделок."

Для каждого исследования зафиксировать:

- scanner;
- direction;
- symbols;
- timeframe;
- period;
- baseline parameters;
- изменяемые параметры;
- диапазоны параметров;
- критерии сравнения.

---

# 5. Baseline обязателен

Перед оптимизацией сначала выполнить baseline run с текущими production-настройками.

Baseline является контрольной группой.

Все новые конфигурации сравнивать именно с ним.

**Без baseline запрещено делать вывод: "новые параметры стали лучше".**

---

# 6. Оптимизация параметров

Допускаются:

- grid search;
- bounded parameter search;
- последовательные эксперименты;
- двухэтапный coarse → fine search.

Не начинать сразу с огромного пространства параметров.

Предпочтительный процесс:

1. выбрать 1–3 наиболее значимых параметра;
2. выполнить coarse search;
3. определить перспективную область;
4. выполнить fine search;
5. проверить найденную конфигурацию на других данных.

Следить за комбинаторным взрывом.

Перед запуском большого grid search рассчитать количество комбинаций:

```
parameter combinations × symbols × directions × periods
```

и сообщить размер исследования.

---

# 7. Метрики

Для каждого run по возможности анализировать:

- setups;
- closed trades;
- wins;
- losses;
- win rate;
- total R;
- average R;
- median R;
- expectancy;
- profit factor;
- total PnL;
- average PnL;
- max drawdown;
- maximum losing streak;
- average holding time;
- Stop Loss count;
- TP count;
- expired count;
- profitable expired count.

**Одна метрика не должна использоваться как единственный критерий оптимизации.**

Особенно запрещено выбирать настройки только по:

- win rate;
- total PnL;
- максимальному R одной сделки.

---

# 8. Минимальный размер выборки

Всегда учитывать количество сделок.

Результат `+3R на 6 сделках` не является более убедительным, чем `+20R на 500 сделках` только потому, что первая конфигурация имеет больший average R.

Конфигурации с маленькой выборкой помечать как `INSUFFICIENT_SAMPLE`.

**Не рекомендовать production-настройки на основании статистически слабой выборки.**

---

# 9. Защита от overfitting

Главная опасность оптимизации — подобрать параметры под конкретный исторический участок.

Поэтому использовать разделение данных.

Предпочтительно:

| Период | Назначение |
|--------|------------|
| TRAIN | Оптимизация параметров |
| VALIDATION | Проверка лучшей конфигурации |
| OUT-OF-SAMPLE | Финальная проверка |

Пример разбиения:

- TRAIN: 2024-01-01 — 2024-12-31
- VALIDATION: 2025-01-01 — 2025-06-30
- OUT-OF-SAMPLE: 2025-07-01 — 2025-12-31

Если данных недостаточно, допускается минимум:

- optimization period;
- independent validation period.

**Нельзя выбирать лучшие параметры и оценивать их качество только на одном периоде.**

---

# 10. Проверка между монетами

Оптимальные параметры не должны определяться только на BTCUSDT.

По возможности использовать разные типы инструментов:

- BTC (BTCUSDT);
- ETH (ETHUSDT);
- крупные altcoins (SOLUSDT, BNBUSDT, etc.);
- высоковолатильные altcoins;
- менее волатильные инструменты.

Отдельно анализировать:

- aggregate performance;
- performance by symbol.

**Настройки, которые работают великолепно на одной монете и плохо на остальных, считать потенциально переобученными.**

---

# 11. Проверка между market regimes

По возможности исследовать разные рыночные режимы:

- trend up;
- trend down;
- range;
- high volatility;
- low volatility.

Если исторический период содержит только один режим, обязательно отметить ограничение исследования.

---

# 12. Стабильность параметров

Не считать оптимальным параметр только потому, что одна конкретная точка дала максимум.

Предпочитать устойчивые области параметров.

Пример устойчивой области:

| Parameter | Expectancy |
|-----------|------------|
| 0.55 | 0.14R |
| **0.60** | **0.15R** |
| 0.65 | 0.14R |

Пример неустойчивой (peerak):

| Parameter | Expectancy |
|-----------|------------|
| 0.55 | 0.01R |
| **0.60** | **0.30R** |
| 0.65 | -0.05R |

Второй вариант может быть случайным локальным максимумом.

---

# 13. Сравнение результатов

Для каждого кандидата формировать таблицу:

| Parameter set | Trades | Win rate | Avg R | Total R | PF | Max DD | Validation |
|---------------|-------:|---------:|------:|--------:|---:|-------:|------------|
| Baseline | 120 | 42% | 0.08R | 9.6R | 1.3 | -4.2R | — |
| Candidate A | 115 | 45% | 0.12R | 13.8R | 1.5 | -3.8R | +2.1R |
| Candidate B | 95 | 48% | 0.15R | 14.3R | 1.7 | -5.1R | +0.5R |

Обязательно включать baseline.

Отдельно показывать процент изменения относительно baseline.

---

# 14. Итоговая классификация

Каждую протестированную конфигурацию относить к одной категории:

### REJECT
Конфигурация хуже baseline или имеет неприемлемый риск.

### INSUFFICIENT_DATA
Недостаточно сделок или исторических данных.

### INTERESTING
Есть улучшение, но требуется дополнительная проверка.

### VALIDATED
Улучшение подтверждается validation/out-of-sample тестом.

### PRODUCTION_CANDIDATE
Конфигурация достаточно стабильна между периодами, монетами и market regimes, и может рассматриваться для изменения production-настроек.

**Статус `PRODUCTION_CANDIDATE` не означает автоматическое изменение production-кода.**

---

# 15. Изменения production-кода

Никогда автоматически не менять настройки `trad_bot` только потому, что backtest показал лучший результат.

Сначала предоставить:

- текущие production-параметры;
- предлагаемые параметры;
- baseline;
- результаты optimization;
- validation;
- out-of-sample;
- количество сделок;
- риски;
- ожидаемый эффект.

**Изменение production-кода является отдельной задачей.**

---

# 16. Воспроизводимость

Каждый эксперимент должен быть воспроизводим.

Фиксировать:

- Git commit `trad_bot`;
- Git commit `trad_bot_backtest`;
- scanner;
- parameters;
- symbols;
- timeframes;
- date range;
- направление;
- версию исторических данных или дату загрузки;
- run_id;
- timestamp.

Если код изменился между двумя экспериментами, результаты нельзя напрямую сравнивать без проверки изменений.

---

# 17. Работа с Git

Перед изменением кода выполнить:

```powershell
git status -sb
```

Не изменять код поверх неизвестных незакоммиченных изменений.

Для разработки использовать отдельную feature/fix ветку.

Не выполнять:

- `reset --hard`;
- `clean -fd`;
- `force push`;
- удаление чужих изменений;

без явного указания пользователя.

---

# 18. Работа с БД

Backtest использует PostgreSQL.

Схема определена в `app/db/schema.sql`.

Основные схемы:

| Schema | Назначение |
|--------|------------|
| `raw` | Сырые данные |
| `market` | Инструменты и свечи |
| `config` | Параметры и parameter sets |
| `bt` | Backtest runs, setups, outcomes |
| `analytics` | Агрегированная аналитика |

Перед написанием SQL **не предполагать** структуру таблицы по памяти.

Если структура не подтверждена — сначала посмотреть schema или описание таблицы через `sql_get_schema`, `sql_describe_table`, `sql_get_table_comments`.

Не удалять результаты прошлых исследований без явного запроса.

---

# 19. Порядок исследования нового сканера

Когда пользователь говорит: **"Оптимизируй SCANNER_NAME"** — агент должен действовать следующим образом.

## STEP 1 — Scanner Inspection

Изучить текущий production-код сканера в `D:\py_pro\trad_bot`.

Составить список параметров, их типов и значений по умолчанию.

## STEP 2 — Backtest Compatibility

Проверить, что `trad_bot_backtest` использует эту же реализацию через `ProductionScannerAdapter`.

## STEP 3 — Data Coverage

Проверить доступные symbols, timeframes и date ranges в PostgreSQL.

## STEP 4 — Baseline

Выполнить baseline с текущими production-настройками.

## STEP 5 — Hypothesis

Определить, какие параметры имеет смысл оптимизировать и почему.

## STEP 6 — Search Space

Сформировать ограниченное пространство параметров.

## STEP 7 — Optimization

Запустить серию backtests (grid search или последовательные эксперименты).

## STEP 8 — Ranking

Отсортировать результаты не только по доходности, но и по:

- expectancy;
- drawdown;
- sample size;
- stability.

## STEP 9 — Validation

Проверить лучших кандидатов на независимом периоде.

## STEP 10 — Cross-Symbol Validation

Проверить на других монетах.

## STEP 11 — Recommendation

Предоставить итог.

---

# 20. Формат итогового отчёта

После исследования выдавать отчёт следующей структуры.

## Scanner
Название сканера.

## Goal
Какую гипотезу проверяли.

## Baseline
Текущие production-параметры и результат.

## Dataset
Монеты, таймфреймы и периоды.

## Search Space
Какие параметры исследовались.

## Results
Лучшие конфигурации в виде таблицы (см. п. 13).

## Stability
Насколько результат устойчив между соседними параметрами, периодами и монетами.

## Validation
Результат независимой проверки.

## Risks
Основные ограничения исследования.

## Recommendation
Один из выводов:

- оставить production параметры;
- продолжить исследование;
- новый parameter set является перспективным;
- parameter set можно считать production candidate.

## Production Change
Чётко указать:

- `NO CHANGE`
- или `PROPOSED CHANGE` с перечислением конкретных параметров.

---

# 21. Принцип принятия решений

Цель оптимизации:

**не найти исторически максимальную прибыль, а найти параметры, которые дают достаточно устойчивое положительное математическое ожидание при приемлемом риске и сохраняют эффективность на данных, которые не использовались для подбора параметров.**

Предпочитать:

| Предпочтение | Рationale |
|---------------|-----------|
| robustness > peak historical result | Устойчивость важнее пика |
| validation > training result | Валидация подтверждает |
| expectancy + risk > win rate | Комплексная оценка |
| large sample > lucky small sample | Статистическая значимость |
| cross-symbol stability > single-symbol optimum | Обобщаемость |
| simple parameters > overfitted complexity | Устойчивость |

---

# 22. Если пользователь просит "найди лучшие настройки"

Не выдавать результат сразу.

Сначала определить:

1. какой scanner;
2. какие параметры реально можно менять;
3. какие исторические данные доступны;
4. какой baseline;
5. размер пространства поиска.

После этого провести эксперимент и только затем давать рекомендацию.

---

# 23. Запрещённые действия

Без явного указания пользователя запрещено:

- включать live trading;
- менять live safety gates;
- изменять production-параметры;
- менять risk limits;
- удалять historical data;
- удалять результаты предыдущих backtests;
- force push;
- менять main напрямую;
- интерпретировать маленькую выборку как доказательство эффективности;
- оптимизировать и валидировать параметры на одном и том же наборе данных.

---

# 24. Главный вопрос агента

При любом результате агент должен отвечать не только:

> "Какая настройка заработала больше?"

но и:

> "Есть ли основания считать, что это улучшение повторится на новых данных?"

---

# 25. CLI команды проекта

## Запуск backtest

```powershell
cd D:\py_pro\trad_bot_backtest
python -m scripts.run_backtest --scanner TREND_PULLBACK --direction LONG --from 2025-01-01 --to 2025-06-30 --symbols BTCUSDT ETHUSDT SOLUSDT
```

## Экспорт результатов

```powershell
python -m scripts.export_backtest --run-id <UUID1> --run-id <UUID2>
```

## Оптимизация (grid search)

```powershell
python -m scripts.optimize_scanner --scanner TREND_PULLBACK --direction LONG --method grid --trials 100
```

## Анализ runs

```powershell
python -m scripts.analyze_runs
```

## Загрузка исторических данных

```powershell
python -m scripts.download_history
```

---

# 26. Структура проекта

```
trad_bot_backtest/
├── app/
│   ├── analytics/       # Метрики, walk-forward, composite objective
│   ├── backtest/        # Level 1 signal/outcome engine
│   ├── data/            # HistoricalDataProvider, resampler, clock
│   ├── db/              # schema.sql, подключение к PostgreSQL
│   ├── optimizer/       # Grid search, parameter space
│   └── scanners/        # ProductionScannerAdapter (bridge к trad_bot)
├── scripts/             # CLI entry points
├── tests/               # Unit tests
├── exports/             # Экспорт результатов backtest
└── SKILL.md             # Данный файл
```

---

# 27. Интеграция с production scanners

```python
from app.scanners.adapters import add_production_project, ProductionScannerAdapter

# Указываем путь к production проекту
add_production_project(r"D:\py_pro\trad_bot")

# Создаём адаптер production scanner
adapter = ProductionScannerAdapter(scanner, context_builder)

# Передаём в backtest engine
backtest = SignalBacktest(adapter.scan, ...)
```

Production scanner НЕ копируется в backtest проект — он используется напрямую из `D:\py_pro\trad_bot`.

---

# 28. PostgreSQL подключение

Настройки подключения через переменные окружения:

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `PGHOST` | Хост | localhost |
| `PGPORT` | Порт | 5432 |
| `PGDATABASE` | Имя БД | trad_bot_backtest |
| `PGUSER` | Пользователь | — |
| `PGPASSWORD` | Пароль | — |

**Важно:** Используйте отдельную БД `trad_bot_backtest`, НЕ production БД.

---

# 29. Ключевые SQL запросы для анализа

## Просмотр доступных данных

```sql
SELECT symbol, timeframe, MIN(open_time), MAX(open_time), COUNT(*)
FROM market.candle
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;
```

## Просмотр результатов backtest

```sql
SELECT run_id, scanner, direction, symbol, 
       setups_count, trades_count, win_rate, total_r, expectancy
FROM bt.run
ORDER BY created_at DESC;
```

## Сравнение конфигураций

```sql
SELECT r.scanner, r.parameters, r.direction,
       COUNT(o.id) as trades,
       AVG(o.r_value) as avg_r,
       SUM(CASE WHEN o.r_value > 0 THEN 1 ELSE 0 END)::float / COUNT(o.id) as win_rate
FROM bt.run r
JOIN bt.outcome o ON o.run_id = r.id
WHERE r.scanner = 'TREND_PULLBACK'
GROUP BY r.id, r.scanner, r.parameters, r.direction
ORDER BY avg_r DESC;
```

---

# 30. Рекомендуемый workflow исследования

```
User: "Исследуй SCANNER_NAME"
    │
    ▼
STEP 1: Scanner Inspection (trad_bot)
    │   → Прочитать код сканера
    │   → Определить параметры и их типы
    │
    ▼
STEP 2: Backtest Compatibility
    │   → Проверить adapters.py
    │   → Убедиться что production scanner используется
    │
    ▼
STEP 3: Data Coverage
    │   → SELECT из market.candle
    │   → Определить доступные символы и периоды
    │
    ▼
STEP 4: Baseline
    │   → Запустить backtest с production params
    │   → Сохранить результаты
    │
    ▼
STEP 5: Hypothesis
    │   → Определить 1-3 параметра для оптимизации
    │   → Сформулировать гипотезу
    │
    ▼
STEP 6: Search Space
    │   → Определить диапазоны параметров
    │   → Рассчитать количество комбинаций
    │
    ▼
STEP 7: Optimization
    │   → Grid search или sequential experiments
    │   → Сохранить все результаты
    │
    ▼
STEP 8: Ranking
    │   → Отсортировать по expectancy, drawdown, sample size
    │   → Выбрать TOP-5 кандидатов
    │
    ▼
STEP 9: Validation
    │   → Проверить TOP-5 на validation period
    │   → Оставить стабильных кандидатов
    │
    ▼
STEP 10: Cross-Symbol
    │   → Проверить на других монетах
    │   → Определить стабильность
    │
    ▼
STEP 11: Recommendation
        → Итоговый отчёт
        → REJECT / INTERESTING / VALIDATED / PRODUCTION_CANDIDATE
        → NO CHANGE или PROPOSED CHANGE
```

---

# 31. Примеры сценариев использования

## Сценарий 1: Оптимизация одного сканера

> "Оптимизируй TREND_PULLBACK на BTCUSDT за последний год"

Агент выполнит:

1. Inspection production-кода TREND_PULLBACK
2. Проверку данных для BTCUSDT
3. Baseline с текущими настройками
4. Grid search по 2-3 параметрам
5. Ranking и validation
6. Итоговый отчёт

## Сценарий 2: Сравнение сканеров

> "Сравни TREND_PULLBACK и BREAKOUT на ETHUSDT за Q1 2025"

Агент выполнит:

1. Inspection обоих сканеров
2. Baseline для каждого
3. Сравнение метрик
4. Рекомендацию

## Сценарий 3: Cross-symbol анализ

> "Проверь, работают ли текущие настройки RSI_REVERSAL на разных монетах"

Агент выполнит:

1. Inspection RSI_REVERSAL
2. Baseline на BTCUSDT
3. Тест на 5+ монетах
4. Анализ стабильности
5. Рекомендацию

## Сценарий 4: Walk-forward

> "Проведи walk-forward анализ для BOLLINGER_SQUEEZE"

Агент выполнит:

1. Inspection сканера
2. Разбиение данных на windows
3. Optimization на каждой train window
4. Validation на каждой test window
5. Анализ стабильности параметров
6. Рекомендацию
