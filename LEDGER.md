# Ledger — Skipped & Problematic Things (steps 00–09)

Generated 2026-11-03, after `restore/09`. Source: PROGRESS.md, code `shortcut:`/`skipped:` notes, and per-step reports.

## Deliberately skipped (would not change correctness now)

| # | Item | Where | Why / risk |
|---|------|-------|------------|
| 1 | **Ollama models never pulled** (~4.5 GB) | step 02 | Live check exits 2 by design. Steps 10–12 (LLM client, workers) will be blind until `python scripts/check_ollama.py --pull`. Biggest pending thing. |
| 2 | **No `.env` file; `GITHUB_TOKEN` empty** | step 01 | Live ingestion runs unauthenticated → GitHub search rate limit is ~10 req/min instead of 30. Works, just slow; `RateLimited` handling exists. |
| 3 | **GitPython skipped → subprocess git** | step 06 | Design §4 mentions GitPython; the task demanded exact `-c` flags, so subprocess is smaller and more faithful. |
| 4 | **GraphQL skipped → REST search only** | step 04 | Design said "REST/GraphQL"; REST covers the need. |
| 5 | **Client doesn't retry/wait itself** | step 04→05 | `RateLimited(wait_seconds)` is raised; the ingestion loop sleeps. One retry policy, in one place. |
| 6 | **`MAX_PAGES = 10` search cap** | step 04 | GitHub search caps at 1000 results anyway; marked with a `shortcut:` comment. |
| 7 | **`.txt` not in allow-list** → `requirements.txt`/`LICENSE` dropped | step 07 | Faithful to §3.2 "core source + README". One-line constant if you want them back. |
| 8 | **Entry points = exact stem match** `{main, __main__, cli, app, agent}` | step 08 | A repo whose real entry is `run.py`/`server.py` gets no code chunks (tree + README still feed Model A). |
| 9 | **chars/4 token estimate; non-Python entries stay raw** | step 08 | Crude by design (§4). JS/Go/… files are chunked verbatim, no signature extraction. |
| 10 | **Security candidates = regex heuristics, not semantic** | step 08 | `shortcut:` comment in code — upgrade path is an AST/taint pass in the dedicated security worker (step 12). |
| 11 | **No success-side events** (only `FAILED_AUDIT`) | step 09 | Design only mandates the failure event; status column shows `PROCESSED`. Add if step 15's SSE feed wants richer telemetry. |
| 12 | **`--once` exit code always 0** | step 09 | Chosen so cron/CI doesn't read "processed 3 repos" as failure. Diverges slightly from `python -m ingestion`. |
| 13 | **No conftest.py / pytest config** | step 01 | Step-01 acceptance forbade extra files → every test repeats the 1-line `sys.path` shim. Also: `pytest-asyncio` and `ollama` are in requirements.txt but currently unused (tests use `asyncio.run`; check_ollama uses httpx). |
| 14 | **Rollback branches stay local** | step 00 | Publishing `rollback/*` to origin needs force-push, which the protocol forbids; rollback.sh prints make-main instructions instead. |
| 15 | **Steps 10–17 not started** | — | LLM client, both workers, analysis service, report, FastAPI+SSE, Streamlit, runner. |

## Problems found and fixed along the way (now guarded by tests/notes)

- **sqlite3 RETURNING + commit** — "SQL statements in progress" crash in `claim_next`; cursor must close before commit (step 03, in PROGRESS notes).
- **Windows: git's read-only `.git`** — `rmtree(ignore_errors=True)` silently left `.git` behind; `_rmtree_force` chmod-retry added (step 06).
- **Module docstring dropped by chunker** — a `join` omitted the `lines` list; the test caught it pre-commit (step 08).
- **CRLF corrupting `.sh` scripts** — `.gitattributes` added, tag `restore/00-r2`; scripts must run under Git Bash (PATH `bash` is WSL and can't see `D:\`).
- **PS execution policy blocks venv activate** — PATH-prepend workaround instead.
- **cp1252 console** — script print messages kept ASCII-only.
- **`.gitignore` swallowed `vault/.gitkeep`** — fixed in `restore/01-r2`.
- **Unrelated histories on first push** — remote already had `readme` + design doc; merged once, since then pushes are clean.
- **Transient `Connection reset` to github.com** early in the session — gone after credentials were stored; all pushes since have succeeded.

## Open questions / process debt

- **Queue priority assumption**: `claim_next` takes highest-stars first (design never specified) — one SQL line to change to FIFO.
- **`REPO_CACHE_DIR=/tmp/repo_cache` on Windows** resolves to `<current drive>:\tmp\repo_cache`; works, but pin it in `.env` if you care.
- **Invented defaults**: `sentinel.db`, 300 s poll, 120 s LLM timeout — not from the design doc.
- **DECISIONS.md is stale** — only the step-00 entry exists; steps 01–09's non-obvious choices (subprocess-vs-GitPython, sync processor, stars-first, the JSON artifact convention) went into PROGRESS instead.

Worth action before/around step 10: the model pull (#1), the token (#2), backfilling DECISIONS.md.
