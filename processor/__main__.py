"""Entry point: python -m processor [--once]."""
import argparse

from processor import service


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m processor")
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
