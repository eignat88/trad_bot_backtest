"""CLI entry point; concrete scanner wiring belongs in a user integration module."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone

def main() -> int:
    parser = argparse.ArgumentParser(description="Run a historical scanner signal backtest")
    parser.add_argument("--scanner", required=True); parser.add_argument("--direction", choices=("LONG", "SHORT"))
    parser.add_argument("--from", dest="start", required=True); parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--symbols", nargs="+", required=True); parser.add_argument("--production-root", default="../trad_bot")
    args = parser.parse_args()
    datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc); datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    print(f"Backtest request accepted: {args.scanner} {args.direction or 'BOTH'} {args.start}..{args.end}; wire DB/scanner adapter in deployment configuration.")
    return 0
if __name__ == "__main__": raise SystemExit(main())
