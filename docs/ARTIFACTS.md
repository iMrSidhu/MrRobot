# Per-scan artifacts — frontend pointer map

One scan of one repo (one `repositories` row) can produce **5 artifact types**.
All are keyed by the **sanitized repo name** (`owner/repo` → `owner_repo`):
dir/file name via `processor.clone.sanitize_dir_name`, vault file via
`llm_engine.report.report_filename` (`owner/repo` → `owner__repo.md`).

## 1. Generated files on disk

| # | Artifact | Path pattern | Written by | Format / top-level shape | Lifecycle | Frontend need |
|---|----------|--------------|-----------|--------------------------|-----------|---------------|
| A | Processed dossier | `<repo_cache>/owner_repo.processed.json` | processor service | `ProcessedRepo`: `repo_id, name, tree_text, readme_chunks[], code_chunks[], security_candidate_files[]` | input for LLM stages; survives clone cleanup, overwritten per re-run | internal — **not served by API** (only for a future "what the model saw" view) |
| B | Synthesis result | `<repo_cache>/owner_repo.synthesis.json` | llm_engine service (stage 1) | `SynthesisResult`: `architecture: str, marketing_claims: str[], verified_reality: str[], gaps: str[], capability_tags: str[]` | rewritten on re-analysis | **center panel** (via API) |
| C | Security findings | `<repo_cache>/owner_repo.security.json` | llm_engine service (stage 2) | `SecurityResult`: `findings: [{severity: 'LOW\|MEDIUM\|HIGH\|CRITICAL', file: str, line: int, description: str, mitigation: str}]` | rewritten on re-analysis | **right panel** (via API) |
| D | Human-readable report | `<vault_dir>/owner__repo.md` | llm_engine report | Markdown, sections: `# name`, `**Stars:** n \| **Link:** url`, `## Architecture`, `## Marketing vs Reality`, `## Capability tags`, `## Vulnerability matrix`, `## Action items`; **no timestamp inside** (REPORTED events are the timeline); overwritten per re-run | final deliverable | **right/bottom panel raw markdown** via `GET /repos/{id}/report` |
| E | DB row + event timeline | `repositories` / `events` tables (SQLite, `settings.db_path`) | all services | row columns `id, name, url, stars, status, synthesis_path, security_report_path, security_json_path, error, timestamp`; events rows `id, repo_id, type, message, payload_json, timestamp` | permanent, append-only | **left radar** (SSE) + **repo table** (`/repos`) |

`<repo_cache>` = `REPO_CACHE_DIR` from `.env`/config; `<vault_dir>` = `VAULT_DIR`.
The transitory clone dir `<repo_cache>/owner_repo/` is **deleted after every run**
(success or failure) — never point the UI at it.

## 2. Which DB column points where (and when it becomes non-NULL)

| status (per repo) | `synthesis_path` | `security_json_path` | `security_report_path` | `error` |
|---|---|---|---|---|
| `QUEUED` `CLONING` `PROCESSED` | — | — | — | — |
| `ANALYZING` | — | — | — | — |
| `ANALYZED` | B path | C path | — | — |
| **`DONE`** | B path | C path | **D path** | — |
| `FAILED_AUDIT` (any stage) | whatever was set before the crash, else — | — | — | `"ExcType: message"` |

So: **`DONE` ⇒ B, C, D all exist.** Partial B exists whenever you see a
`SYNTHESIS_DONE` event; the DB marks `ANALYZED` only when both JSONs are on disk.

## 3. HTTP endpoints to point the frontend at

| Endpoint | Returns | Use for |
|---|---|---|
| `GET /health` | `{status:'ok', db}` | readiness badge |
| `GET /repos` | list of full rows (columns above, incl. all 3 path columns + `error`) | repo table; filter `status=='DONE'` for "has report" |
| `GET /repos/{id}` | `{repo: row, synthesis: SynthesisResult\|null, security: SecurityResult\|null}` — JSONs **inlined** from B/C paths | center + right panels; render directly from this, don't touch the filesystem |
| `GET /repos/{id}/report` | `{path, markdown}` for artifact D; `404` until DONE/no file, `400` if stored path escapes `VAULT_DIR` | render the full human report anywhere |
| `GET /events/stream` | SSE, `id: <event_id>`, `event: <type>`, `data:{id,repo_id,type,message,payload,timestamp}` | radar feed; reconnect honors `Last-Event-ID` |

## 4. Event types per successful scan (order guaranteed by id)

`DISCOVERED` (ingestion, once) → `ANALYSIS_START` → `SYNTHESIS_DONE`
(payload `{capability_tags}`) → `SECURITY_DONE` (payload `{findings: count}`) →
`REPORTED` (message contains the vault md path). Failures emit
`FAILED_AUDIT` (per repo) or `RATE_LIMIT` / `ERROR` (repo_id NULL, ingestion).
Processor stages (clone/filter/chunk) intentionally emit **no events**.

## 5. Gaps to know before building

1. ~~The vault `.md` has no serving route~~ **RESOLVED**: `GET
   /repos/{id}/report` → `{"path":…, "markdown":…}` (404 until the repo has a
   report; traversal-guarded to `VAULT_DIR` — a hostile DB row can never make
   the API read outside the vault).
2. A repo that **re-analyzes** overwrites B/C/D in place — history lives only in
   `events` rows (timestamps there, not in the files).
3. `verified_reality`/`gaps` are currently `[]` by design (README-only synthesis
   config you chose earlier) — center panel should render the claims table
   gracefully with an empty reality column.
