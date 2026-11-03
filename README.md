# GitHub Capability & Security Sentinel

Autonomous scanner that discovers high-impact AI GitHub repos, clones them safely (read-only),
runs dual local-LLM capability + security pipelines, writes Markdown briefings to `vault/`,
and streams results to a local dashboard. Design: `docs/DESIGN.md` — work rules: `AGENT_PROTOCOL.md`.

## Local setup

1. **Install & start Ollama** — <https://ollama.com/download> (Windows installer runs a tray
   server; or start with `ollama serve`).
2. **Respect the 6GB VRAM budget** (DESIGN.md §2.3) — set these where Ollama runs:
   - `OLLAMA_MAX_LOADED_MODELS=1` — only one model resident at a time.
   - `OLLAMA_KEEP_ALIVE=2m` — unload quickly after each call.
   (Windows: System → Advanced system settings → Environment Variables, or `setx` in a terminal,
   then restart the Ollama app.)
3. **Pull the pipeline models** (defaults from `shared/config.py`):
   ```
   ollama pull qwen2.5-coder:3b   # Model A — capability synthesis
   ollama pull phi3:mini          # Model B — security audit
   ```
4. **Verify readiness**:
   ```
   python scripts/check_ollama.py           # server + models + latency + VRAM report; non-zero exit on problems
   python scripts/check_ollama.py --pull    # auto-fetch missing models first
   ```
5. **Python deps**: `python -m venv .venv` then install `requirements.txt` (or at minimum
   `httpx python-dotenv pytest` to run the tests).

## Environment variables

Copy `.env.example` to `.env` (or export directly); all defaults live in `shared/config.py`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GITHUB_TOKEN` | empty | token for GitHub search (anonymous = 10 req/min) |
| `SEARCH_KEYWORDS` | `ai agent, harness, autonomous, llm framework` | comma-separated discovery terms |
| `MIN_STARS` | `1000` | search filter `stars:>N` |
| `DB_PATH` | `sentinel.db` | SQLite queue + event log (WAL, shared by services) |
| `REPO_CACHE_DIR` | `/tmp/repo_cache` | scratch clones + JSON artifacts (on Windows: `<drive>:\tmp\repo_cache`) |
| `VAULT_DIR` | `vault` | Markdown reports land here |
| `OLLAMA_HOST` | `http://localhost:11434` | local model server |
| `SYNTHESIS_MODEL` / `SECURITY_MODEL` | `qwen2.5-coder:3b` / `phi3:mini` | Models A / B |
| `POLL_INTERVAL_SEC` | `300` | idle worker sleep |
| `LLM_TIMEOUT_SEC` | `120` | per-call timeout (retried once) |
| `CONTEXT_BUDGET_TOKENS` | `6000` | prompt packing budget (~4 chars/token) |

## Running

One command starts all five services (ingestion, processor, llm_engine, API, HUD) with
crash-restart + exponential backoff; Ctrl+C stops everything:

```
python scripts/run_all.py
```

- HUD: <http://localhost:8501> · API + SSE: <http://localhost:8000> (`/docs` is disabled; endpoints
  are `/health`, `/repos`, `/repos/{id}`, `/events/stream`).
- Ports: `SENTINEL_API_PORT`, `SENTINEL_HUD_PORT`.
- Or run a single service manually for debugging: `python -m ingestion|processor|llm_engine [--once]`,
  `python -m uvicorn dashboard.api:app`, `streamlit run dashboard/app.py`.

## Demo without models

```
python scripts/seed_demo.py     # fake repos + events + artifacts (idempotent)
streamlit run dashboard/app.py  # three-panel HUD; works with no API/Ollama running
```

Reset demo state: delete `sentinel.db`, `vault/*` and the cache dir contents (all gitignored).

## Tests

```
pytest            # fully offline: fake GitHub/Ollama transports, local git fixtures
```

## Troubleshooting

- **Ollama unreachable / models missing** - `python scripts/check_ollama.py --pull` (exit 1: server
  down; exit 2: models absent; exit 3: probe failed). Slow first call per model = load time.
- **Everything lands in `FAILED_AUDIT`** - check the `error` column via
  `sqlite3 sentinel.db "select name,status,error from repositories"` or the event radar; the
  pipeline never stops on one bad repo.
- **GitHub `403/429`** - rate-limited: ingestion writes a `RATE_LIMIT` event and waits it out;
  set `GITHUB_TOKEN` for 30 req/min search throughput.
- **Windows**: run the bash scripts with Git Bash, not the WSL `bash` on PATH
  (`"C:\Program Files\Git\bin\bash.exe" scripts/checkpoint.sh ...`). PowerShell may block
  `.venv` activation - prepend `$PWD\.venv\Scripts` to `$env:Path` instead.
- **Locked database** - WAL mode is enabled for exactly this; if a crashed process left a stale
  `-wal`/`-shm` file, stop services and delete them.

## Workflow: prompts and restore tags

Work is executed step by step (`prompts/INDEX.md` -> `prompts/step-NN-*.md`), each step ending in a
checkpoint: `scripts/checkpoint.sh 07 'file filter'` runs the test suite, commits, tags
`restore/07` (repeat runs bump `-r2`, `-r3`, ...) and pushes both. To inspect or rewind a state
non-destructively: `scripts/rollback.sh restore/07` creates a `rollback/...` branch from that tag
(saving any uncommitted work to a `backup/...` branch first) and prints how to promote it. Current
status lives in `PROGRESS.md`; design is authoritative in `docs/DESIGN.md`.
