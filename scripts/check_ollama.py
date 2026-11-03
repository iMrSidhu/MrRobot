#!/usr/bin/env python
"""Check Ollama readiness: server reachable, models pulled, tiny-prompt latency, VRAM.

DESIGN.md §4 (Tech Stack) / §5 Step 1.2.
Exit codes: 0 ok, 1 server unreachable, 2 models missing, 3 probe failed/timed out.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from shared.config import load_settings  # noqa: E402


def get_client(host: str, timeout: float = 10.0) -> httpx.Client:
    return httpx.Client(base_url=host, timeout=timeout)


def installed_models(client) -> set[str]:
    resp = client.get("/api/tags")
    if resp.status_code != 200:
        raise httpx.HTTPError(f"unexpected status {resp.status_code}")
    return {m["name"] for m in resp.json().get("models", [])}


def pull_model(client, name: str) -> bool:
    try:
        resp = client.post("/api/pull", json={"name": name, "stream": False}, timeout=3600)
        return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def probe(client, name: str, timeout: float) -> float | None:
    """One tiny prompt against the model; returns latency seconds or None on failure."""
    t0 = time.monotonic()
    try:
        resp = client.post(
            "/api/generate",
            json={
                "model": name,
                "prompt": "Reply with exactly: OK",
                "stream": False,
                "options": {"num_predict": 8},
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
    except (httpx.HTTPError, OSError):
        return None
    return time.monotonic() - t0


def print_vram(context: str) -> None:
    if shutil.which("nvidia-smi") is None:
        print(f"VRAM [{context}]: nvidia-smi not found, skipping")
        return
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        out = f"nvidia-smi failed: {exc}"
    print(f"VRAM [{context}]: {out}")


def check(pull: bool = False) -> int:
    s = load_settings()
    print(f"Ollama: {s.ollama_host}")
    client = get_client(s.ollama_host)
    try:
        try:
            models = installed_models(client)
        except (httpx.HTTPError, OSError):
            print(f"ERROR: cannot reach Ollama at {s.ollama_host} - is `ollama serve` running?")
            print("Install it from https://ollama.com/download (DESIGN.md §5 Step 1.2)")
            return 1

        needed = [s.synthesis_model, s.security_model]
        missing = [m for m in needed if m not in models]
        if missing:
            if not pull:
                print(f"ERROR: models not pulled: {', '.join(missing)} - re-run with --pull or `ollama pull <model>`")
                return 2
            for name in missing:
                print(f"pulling {name} ...")
                if not pull_model(client, name):
                    print(f"ERROR: pull failed for {name}")
                    return 2
                print_vram(f"after pulling {name}")

        code = 0
        for name in needed:
            latency = probe(client, name, s.llm_timeout_sec)
            if latency is None:
                print(f"FAIL: probe timed out/errored for {name} (LLM_TIMEOUT_SEC={s.llm_timeout_sec})")
                code = 3
            else:
                print(f"OK: {name} replied in {latency:.2f}s")
            print_vram(f"after loading {name}")
        return code
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ollama readiness check (DESIGN.md Step 1.2)")
    parser.add_argument("--pull", action="store_true", help="auto-pull missing models before probing")
    args = parser.parse_args()
    sys.exit(check(pull=args.pull))


if __name__ == "__main__":
    main()
