"""Single MOMENTUM_EXHAUSTION backtest - for timing."""
import subprocess, sys, time

cmd = [
    sys.executable, "-m", "scripts.run_backtest",
    "--scanner", "MOMENTUM_EXHAUSTION",
    "--direction", "BOTH",
    "--from", "2025-01-01", "--to", "2025-07-01",
    "--symbols", "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "SUIUSDT", "DOGEUSDT", "HYPEUSDT", "1000PEPEUSDT", "ADAUSDT",
    "--production-root", r"D:\py_pro\trad_bot",
    "--db-name", "trad_bot_backtest",
    "--target-r", "2.0",
]
t0 = time.time()
r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
elapsed = time.time() - t0
print(f"Exit code: {r.returncode}")
print(f"Time: {elapsed:.1f}s")
print(f"Stdout: {r.stdout}")
if r.stderr:
    print(f"Stderr (last 500): {r.stderr[-500:]}")
