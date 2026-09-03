"""Quick test of MOMENTUM_EXHAUSTION - focused on key parameters only."""
import os
import subprocess
import sys
import time

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "SUIUSDT", "DOGEUSDT", "HYPEUSDT", "1000PEPEUSDT", "ADAUSDT"]

def run(label, extra_args=None):
    cmd = [
        sys.executable, "-m", "scripts.run_backtest",
        "--scanner", "MOMENTUM_EXHAUSTION",
        "--direction", "BOTH",
        "--from", "2025-01-01", "--to", "2025-07-01",
        "--symbols", *SYMBOLS,
        "--production-root", r"D:\py_pro\trad_bot",
        "--db-name", "trad_bot_backtest",
    ]
    if extra_args:
        cmd.extend(extra_args)
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - t0
    out = r.stdout.strip()
    print(f"  {label:45s} {out:60s} [{elapsed:.0f}s]")
    return out

print("=== MOMENTUM_EXHAUSTION Quick Sweep (10 symbols, 6 months) ===")
print()

# 1. Natural targets (no override)
print("--- No target_r override (scanner ATR-based targets) ---")
baseline = run("baseline_no_target_r")

# 2. target_r override
print()
print("--- target_r override ---")
for tr in [0.75, 1.0, 1.5, 2.0, 3.0]:
    run(f"target_r={tr}", ["--target-r", str(tr)])

# 3. Direction
print()
print("--- Direction ---")
for d in ["LONG", "SHORT", "BOTH"]:
    run(f"direction={d}", ["--direction", d])

# 4. signal_timeframe
print()
print("--- Signal Timeframe ---")
for tf in ["5m", "15m"]:
    run(f"signal_tf={tf}", ["--signal-timeframe", tf])

# 5. exhaustion_threshold
print()
print("--- Exhaustion Threshold ---")
for eth in [0.001, 0.003, 0.005, 0.008, 0.01]:
    run(f"eth={eth}", ["--exhaustion-threshold", str(eth)])

# 6. swing_lookback
print()
print("--- Swing Lookback ---")
for slb in [3, 5, 7, 10]:
    run(f"slb={slb}", ["--swing-lookback", str(slb)])

# 7. skip_range
print()
print("--- Skip Range ---")
run("skip_range", ["--skip-range"])

# 8. Best combos from quick scan
print()
print("--- Quick Combos ---")
combos = [
    ("slb5_eth3_tr2.0", ["--swing-lookback", "5", "--exhaustion-threshold", "0.003", "--target-r", "2.0"]),
    ("slb5_eth3_tr3.0", ["--swing-lookback", "5", "--exhaustion-threshold", "0.003", "--target-r", "3.0"]),
    ("slb7_eth5_tr2.0", ["--swing-lookback", "7", "--exhaustion-threshold", "0.005", "--target-r", "2.0"]),
    ("slb7_eth5_tr3.0", ["--swing-lookback", "7", "--exhaustion-threshold", "0.005", "--target-r", "3.0"]),
    ("slb10_eth5_tr2.0", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "2.0"]),
    ("slb10_eth8_tr3.0", ["--swing-lookback", "10", "--exhaustion-threshold", "0.008", "--target-r", "3.0"]),
    ("slb5_eth3_tr2_sr", ["--swing-lookback", "5", "--exhaustion-threshold", "0.003", "--target-r", "2.0", "--skip-range"]),
    ("slb7_eth5_tr2_sr", ["--swing-lookback", "7", "--exhaustion-threshold", "0.005", "--target-r", "2.0", "--skip-range"]),
    ("slb10_eth5_tr3_sr", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0", "--skip-range"]),
    ("slb5_eth3_tr2_15m", ["--swing-lookback", "5", "--exhaustion-threshold", "0.003", "--target-r", "2.0", "--signal-timeframe", "15m"]),
    ("slb7_eth5_tr2_15m", ["--swing-lookback", "7", "--exhaustion-threshold", "0.005", "--target-r", "2.0", "--signal-timeframe", "15m"]),
    ("slb10_eth5_tr3_15m", ["--swing-lookback", "10", "--exhaustion-threshold", "0.005", "--target-r", "3.0", "--signal-timeframe", "15m"]),
]
for label, args in combos:
    run(label, args)

print()
print("Done!")
