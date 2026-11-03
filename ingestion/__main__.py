"""Entry point: python -m ingestion [--once]"""
from __future__ import annotations

import argparse
import asyncio

from ingestion.service import run_forever, run_once


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingestion")
    parser.add_argument("--once", action="store_true", help="run a single poll pass and exit")
    args = parser.parse_args(argv)
    asyncio.run(run_once() if args.once else run_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
