# Frontend input contract — what to fetch, what you get

The frontend consumes **five HTTP inputs** served by `dashboard/api.py`
(start with `python -m uvicorn dashboard.api:app --port 8000`). Files on disk
are the backend's private area: **never fetch filesystem paths directly** —
every artifact is echoed through these endpoints (the DB can hold a
CWD-relative path like `vault\colibri.md` that is meaningless to the browser).

## 1. Endpoint inputs (one row per UI element)

| UI element | Input | Response shape | Non-null / ready when |
|---|---|---|---|
| Readiness badge | `GET /health` | `{ "status": "ok", "db": "<sqlite path>" }` | server up |
| Repo table / selector | `GET /repos` | array of rows: `{ id:int, name:str, url:str, stars:int, status:str, synthesis_path:str|null, security_json_path:str|null, security_report_path:str|null, error:str|null, timestamp:str }` | always (empty array = nothing scanned yet); "has a report" ⇔ `status == "DONE"` |
| **Center panel** — architecture + claims | `GET /repos/{id}` → `.synthesis` | `{ "architecture": str, "marketing_claims": str[], "verified_reality": str[], "gaps": str[], "capability_tags": str[] }` | report `404`/`null` until stage 1 wrote B + ANALYZED/DONE set `synthesis_path`. **Caveat: `verified_reality` and `gaps` are currently always `[]`** (README-only synthesis config — claims are extracted, not verified) |
| **Right panel** — vulnerability matrix | `GET /repos/{id}` → `.security` | `{ "findings": [ { "severity": "CRITICAL"\|"HIGH"\|"MEDIUM"\|"LOW", "file": str, "line": int (1-based), "description": str, "mitigation": str } ] }` — pre-sorted CRITICAL→LOW, duplicates merged, every `file:line` verified to exist in the scanned tree | `null` until stage 2 wrote C + `security_json_path` backfilled (happens at DONE). Empty `findings` array is a **good result**, render "No vulnerabilities found." |
| Full human-readable report | `GET /repos/{id}/report` | `{ "path": str, "markdown": str }` (six sections: Architecture, Marketing vs Reality, Capability tags, Vulnerability matrix, Action items; **no timestamp inside**) | `404` "no report yet (status …)" until DONE wrote D; `400` = DB pointer escaped `VAULT_DIR` (should never happen — treat as backend bug); `404` "report file missing" = D deleted after DONE |
| **Left radar** — live feed | `GET /events/stream` (SSE, `text/event-stream`) | per frame: `id: <event_id>` line + `event: <TYPE>` line + `data:` JSON `{ "repo_id": int|null, "type": str, "message": str, "payload": object, "timestamp": str }` (`id` is the SSE field, **not** inside `data`) | immediate backlog replay on connect, then live <1 s after DB commit; reconnect by sending `Last-Event-ID: <last id>` — server resumes after that id |

`/repos/{id}` also returns `{ "repo": <row>, "synthesis": … , "security": … }` —
one call is enough to render the center + right panels for the selected repo.
`synthesis`/`security` are `null` both when not produced yet **and** when the
artifact file was deleted after DONE (the API never 500s on a missing file).

## 2. Status → which inputs are populated

| repo `status` | `.synthesis` | `.security` | `/report` | notes |
|---|---|---|---|---|
| `QUEUED` `CLONING` `PROCESSED` | null | null | 404 | ingestion/processor only |
| `ANALYZING` | null | null | 404 | LLM stages in flight; watch the radar |
| `ANALYZED` (transient) | set | set | 404 | both JSONs on disk, report not yet |
| **`DONE`** | set | set | **200** | full dashboard render possible |
| `FAILED_AUDIT` | whatever survived (may be set) | usually null | 404 | show `row.error` (`"ExcType: message"`) |

## 3. Event types (radar vocabulary, emitted order)

| `type` | `repo_id` | `payload` | meaning / UI action |
|---|---|---|---|
| `DISCOVERED` | id | `{ "url": str, "stars": int }` | ingestion enqueued a repo |
| `RATE_LIMIT` / `ERROR` | null | `{ "wait_seconds": n }` / `{}` | ingestion health; badge only |
| `ANALYSIS_START` | id | `{}` | LLM stages began |
| `SYNTHESIS_DONE` | id | `{ "capability_tags": str[] }` | center panel can refresh |
| `SECURITY_DONE` | id | `{ "findings": int }` (count) | right panel can refresh |
| `REPORTED` | id | `{}`; `message` = "report at <path>" | repo is `DONE`; report tab can open |
| `FAILED_AUDIT` | id | `{}` | mark repo red; read `error` |

Processor stages (clone/filter/chunk) intentionally emit **no events**.
Ordering is guaranteed by increasing event `id`.

## 4. On-disk artifacts (backend internals — for debugging only)

Keyed by sanitized name: `owner/repo` → `owner_repo` sidecars in
`REPO_CACHE_DIR`, `owner__repo.md` in `VAULT_DIR`.

| # | File | Contract it serializes | Relevance to frontend |
|---|---|---|---|
| A | `<cache>/owner_repo.processed.json` | `ProcessedRepo` (tree_text, readme_chunks, code_chunks, security_candidate_files) | none (what the model saw; possible future "evidence" view) |
| B | `<cache>/owner_repo.synthesis.json` | SynthesisResult — same shape as `/repos/{id}.synthesis` | served through the API |
| C | `<cache>/owner_repo.security.json` | SecurityResult — same shape as `/repos/{id}.security` | served through the API |
| D | `<vault>/owner__repo.md` | the six-section Markdown report | served through `/repos/{id}/report` |
| E | `sentinel.db` (`repositories` + `events`, WAL) | source of truth for rows 1–3 above | served through the API |

The transitory clone dir `<cache>/owner_repo/` is deleted after every run —
never reference it.

## 5. Gotchas to code around

1. `url` may be a **local directory path** (test/dev rows like colibri's
   `D:\ai-experiments\GITHUB-Colibri\colibri-main`) — render as text, only
   hyperlink `http(s)://` values.
2. Re-analysis **overwrites B/C/D in place** — history lives only in `events`.
3. `verified_reality`/`gaps` empty by current prompt config — claims table
   needs to render gracefully with an empty reality column.
4. Timestamps are UTC ISO strings (`timestamp` on rows and events).
5. There is no auth/CORS config — the API is designed for localhost only.
