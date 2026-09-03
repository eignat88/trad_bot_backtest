# VPS Deployment Guide

## Быстрый старт (5 шагов)

### 1. Подключиться к VPS

```bash
ssh root@91.99.60.150
```

### 2. Запустить setup

```bash
bash <(curl -s https://raw.githubusercontent.com/eignat88/trad_bot_backtest/main/deploy/vps_setup.sh)
```

Или вручную:
```bash
git clone https://github.com/eignat88/trad_bot_backtest.git /opt/trad_bot_backtest
cd /opt/trad_bot_backtest
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m scripts.apply_schema
```

### 3. Скопировать production scanner

```bash
# С локальной машины:
scp -r D:\py_pro\trad_bot deploy@91.99.60.150:/opt/trad_bot

# Или на VPS:
cd /opt
git clone https://github.com/eignat88/trad_bot.git
```

### 4. Запустить backfill

```bash
ssh deploy@91.99.60.150
cd /opt/trad_bot_backtest
bash deploy/run_backfill.sh
```

### 5. Проверить статус

```bash
bash deploy/check_status.sh
```

---

## Архитектура

```
VPS 91.99.60.150
├── PostgreSQL (trad_bot_backtest)
│   ├── bt.setup          — 306K setups
│   ├── dds.*             — edge research layer
│   └── mart.edge_dataset — ready for discovery
│
├── /opt/trad_bot_backtest
│   ├── app/edge_research/ — features, outcomes, discovery
│   ├── scripts/           — backfill, validate, discover
│   └── deploy/            — VPS deployment scripts
│
├── /opt/trad_bot           — production scanner (read-only)
│
└── screen sessions:
    ├── edge_backfill       — backfill process
    └── edge_discovery      — discovery runs (manual)
```

## Ручные команды

```bash
# Backfill по всем символам
cd /opt/trad_bot_backtest
.venv/bin/python -m scripts.backfill_edge_dataset --batch-size 200

# Backfill по конкретному символу
.venv/bin/python -m scripts.backfill_edge_dataset --symbol btcusdt --batch-size 200

# Backfill за конкретный период
.venv/bin/python -m scripts.backfill_edge_dataset --from 2025-01-01 --to 2025-06-01

# Smoke test (100 setups)
.venv/bin/python -m scripts.backfill_edge_dataset --limit 100 --batch-size 50

# Validate
.venv/bin/python -m scripts.validate_edge_dataset

# Discover edges
.venv/bin/python -m scripts.discover_edges \
    --scanner BREAKOUT_RETEST --direction LONG \
    --feature rsi_14 --feature volume_zscore --feature atr_percentile_30d \
    --min-samples 30
```

## Мониторинг

```bash
# Прогресс backfill
tail -f /tmp/edge_backfill.log

# Последние обработанные
grep "processed:" /tmp/edge_backfill.log | tail -5

# Проверка покрытия
bash deploy/check_status.sh

# Процессы
ps aux | grep backfill
screen -list
```

## Автозапуск (systemd)

Если нужно запускать backfill автоматически при старте VPS:

```bash
sudo cp deploy/edge-backfill.service /etc/systemd/system/
sudo systemctl enable edge-backfill
sudo systemctl start edge-backfill
```

## Troubleshooting

### "insufficient history" > 0
Это нормально — setups в первые дни данных не имеют достаточно свечей для фичей.

### Backfill остановился
```bash
screen -r edge_backfill
# Если сессия мертва:
bash deploy/run_backfill.sh
```

### Ошибка подключения к PostgreSQL
```bash
sudo systemctl status postgresql
sudo -u postgres psql -c "SELECT 1"
```

### Нехватка памяти
```bash
free -h
# Если мало — уменьшите batch-size:
.venv/bin/python -m scripts.backfill_edge_dataset --batch-size 50
```
