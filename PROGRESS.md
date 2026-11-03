# PROGRESS

## Current step
Step 06 done. Next: step 07 — File filter (see prompts/INDEX.md).

## Log
<!-- one entry per finished step, newest first: `05 — what was done — restore/05` -->
- 06 — processor/clone.py clone_repo: depth-1 --no-local clone with 300s timeout into sanitized subdirs of REPO_CACHE_DIR (GIT_TERMINAL_PROMPT=0, GIT_LFS_SKIP_SMUDGE=1, core.hooksPath=/dev/null, core.symlinks=false), immediate .git wipe, cleanup(); failure/timeout leave no partial dirs; 8 tests on local temp repos (no network) incl. malicious-hook-does-not-run — restore/06
- 05 — ingestion/service.py run_once/run_forever (search -> dedupe -> QUEUED insert + DISCOVERED events; RateLimited writes RATE_LIMIT event, sleeps requested seconds, continues; any API error -> ERROR event, never crashes), python -m ingestion [--once] via __main__; 5 tests with fake httpx client — restore/05
- 04 — ingestion/github_client.py: async search_repositories ('<kw> stars:>N', sort=stars, paginated, cross-keyword dedupe, optional token), RateLimited(wait_seconds) from Retry-After / X-RateLimit-Reset / remaining=0; 8 httpx-MockTransport tests, no live network — restore/04
- 03 — shared/models.py pydantic contracts (RepoCandidate, ProcessedRepo, SynthesisResult, Finding, SecurityResult, 7 STATUSES) + shared/db.py SQLite WAL queue/events (dedupe by name, atomic claim_next via UPDATE...RETURNING, event feed); 18 tests green — restore/03
- 02 — scripts/check_ollama.py (--pull, latency probes, nvidia-smi VRAM), README 'Local setup', 5 mocked tests; live run: Ollama reachable, models NOT yet pulled (exit 2) — restore/02
- 01 — service packages, requirements.txt, shared/config.py typed settings, shared/logging.py, .env.example, vault/.gitkeep tracked, tests green (2 passed) — restore/01-r2
- 00 — workflow scaffolding (docs, protocol, scripts, prompts index) — restore/00

## Open questions
- claim_next order: DESIGN.md doesn't specify queue priority → chose highest stars first (`ORDER BY stars DESC, id`); trivial to switch to FIFO.
- DESIGN.md gives no defaults for DB_PATH / POLL_INTERVAL_SEC / LLM_TIMEOUT_SEC → chose `sentinel.db`, 300s, 120s (simplest).
- REPO_CACHE_DIR default `/tmp/repo_cache` (design §3.1) resolves to `<current-drive>:\tmp\repo_cache` on Windows; clone_repo mkdirs parents so it works as-is — override REPO_CACHE_DIR in .env if a specific drive is wanted (revisit only if it bites).
- Ollama server is up on this machine but `qwen2.5-coder:3b` / `phi3:mini` are not pulled (~4.5GB download) — did not auto-pull in step 02 (not in task scope); run `python scripts/check_ollama.py --pull` when ready.

## Notes for next session
- Run only the current step; finish with `scripts/checkpoint.sh <step-id> '<message>'` (AGENT_PROTOCOL.md).
- venv holds pytest, python-dotenv, httpx, pydantic (install others via `.venv\Scripts\python.exe -m pip install ...`). Activate is blocked by PS execution policy — prepend to PATH instead: `$env:Path = "$PWD\.venv\Scripts;$env:Path"` before running checkpoint.sh.
- shared/db.py: sqlite3 + RETURNING requires closing the cursor before conn.commit() ("SQL statements in progress" otherwise).
- processor/clone.py: git clones its objects read-only, so wiping `.git` on Windows needs a chmod-on-PermissionError rmtree (`_rmtree_force`); plain `rmtree(ignore_errors=True)` silently leaves `.git` behind.
- Bash scripts must run under Git Bash (`C:\Program Files\Git\bin\bash.exe`); PATH `bash` here is WSL and can't see `D:\`.
