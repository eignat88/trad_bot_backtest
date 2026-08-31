"""CLI contract for grid/random/Optuna optimization integration."""
from __future__ import annotations
import argparse

def main() -> int:
    p = argparse.ArgumentParser(description="Optimize a production scanner on historical data")
    p.add_argument("--scanner", required=True); p.add_argument("--direction", choices=("LONG", "SHORT"))
    p.add_argument("--method", choices=("grid", "random", "optuna"), default="grid"); p.add_argument("--trials", type=int, default=100)
    args = p.parse_args(); print(f"Optimization request accepted: {args.scanner}, {args.method}, {args.trials} trials")
    return 0
if __name__ == "__main__": raise SystemExit(main())
