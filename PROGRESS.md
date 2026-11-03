# PROGRESS

## Current step
Step 01 done. Next: step 02 — Ollama check (see prompts/INDEX.md).

## Log
<!-- one entry per finished step, newest first: `05 — what was done — restore/05` -->
- 01 — service packages, requirements.txt, shared/config.py typed settings, shared/logging.py, .env.example, tests green (2 passed) — restore/01
- 00 — workflow scaffolding (docs, protocol, scripts, prompts index) — restore/00

## Open questions
- DESIGN.md gives no defaults for DB_PATH / POLL_INTERVAL_SEC / LLM_TIMEOUT_SEC → chose `sentinel.db`, 300s, 120s (simplest).
- REPO_CACHE_DIR default `/tmp/repo_cache` (per design §3.1) resolves to `C:\tmp\repo_cache` on Windows → revisit in step 06 (safe clone).

## Notes for next session
- Run only the current step; finish with `scripts/checkpoint.sh <step-id> '<message>'` (AGENT_PROTOCOL.md).
- Activate the venv first (`& .venv\Scripts\Activate.ps1`) so checkpoint.sh's `python -m pytest` works; it holds pytest + python-dotenv.
- Bash scripts must run under Git Bash (`C:\Program Files\Git\bin\bash.exe`); PATH `bash` here is WSL and can't see `D:\`.
