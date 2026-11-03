"""Entry point: python -m llm_engine [--once]."""
import argparse

from llm_engine import service


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m llm_engine")
    parser.add_argument("--once", action="store_true",
                        help="drain the current queue and exit")
    args = parser.parse_args(argv)
    if args.once:
        service.run_once()
    else:
        service.run_forever()
    return 0


if __name__ == "__main__":
    SystemExit(main())
