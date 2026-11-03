"""Run the whole sentinel as one command (DESIGN.md section 2):
ingestion, processor, llm_engine, the API and the Streamlit HUD as five
independent subprocesses. A supervisor loop restarts any that exit with a
non-zero code, doubling that service's delay per crash (exponential
backoff, capped) and resetting it once the service has stayed up.
Ctrl+C shuts everything down in reverse order.

    python scripts/run_all.py
    python scripts/run_all.py --list     # show commands and exit
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BACKOFF_BASE_SEC = 1.0
BACKOFF_CAP_SEC = 60.0
HEALTHY_RESET_SEC = 60.0  # a service that survives this long forgets its crashes

# name -> command (design 2: each service its own process/VM footprint)
SERVICES = {
    "ingestion": [sys.executable, "-m", "ingestion"],
    "processor": [sys.executable, "-m", "processor"],
    "llm_engine": [sys.executable, "-m", "llm_engine"],
    "api": [sys.executable, "-m", "uvicorn", "dashboard.api:app",
            "--host", "127.0.0.1", "--port", os.environ.get("SENTINEL_API_PORT", "8000")],
    "dashboard": [sys.executable, "-m", "streamlit", "run", "dashboard/app.py",
                  "--server.port", os.environ.get("SENTINEL_HUD_PORT", "8501"),
                  "--server.headless", "true"],
}


def next_delay(crashes: int) -> float:
    """Exponential backoff for the `crashes`-th restart of a service."""
    return min(BACKOFF_BASE_SEC * (2 ** (crashes - 1)), BACKOFF_CAP_SEC)


class Service:
    def __init__(self, name: str, cmd: list[str]):
        self.name, self.cmd = name, cmd
        self.proc: subprocess.Popen | None = None
        self.crashes = 0
        self.started = 0.0
        self.restart_after = 0.0  # monotonic time; 0 = launch immediately

    def launch(self) -> None:
        self.proc = subprocess.Popen(self.cmd, cwd=str(ROOT))
        self.started = time.monotonic()
        print(f"[run_all] started {self.name} (pid {self.proc.pid})")

    def check(self) -> None:
        if self.proc is None:
            if time.monotonic() >= self.restart_after:
                self.launch()
            return
        code = self.proc.poll()
        if code is None:
            if time.monotonic() - self.started > HEALTHY_RESET_SEC:
                self.crashes = 0
            return
        self.proc = None
        if code == 0:
            print(f"[run_all] {self.name} exited cleanly - not restarting")
            return
        self.crashes += 1
        delay = next_delay(self.crashes)
        self.restart_after = time.monotonic() + delay
        print(f"[run_all] {self.name} crashed (code {code}); restart #{self.crashes} "
              f"in {delay:.0f}s")

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        print(f"[run_all] stopping {self.name} (pid {self.proc.pid})")
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true", help="print service commands and exit")
    args = parser.parse_args(argv)
    if args.list:
        for name, cmd in SERVICES.items():
            print(f"{name}: {' '.join(cmd)}")
        return 0

    services = [Service(n, c) for n, c in SERVICES.items()]
    stopping = False

    def on_signal(_sig, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    try:
        for s in services:
            s.launch()
        while not stopping:
            for s in services:
                s.check()
            time.sleep(0.5)
        print("[run_all] shutting down...")
    finally:
        for s in reversed(services):
            s.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
