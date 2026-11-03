# Sentinel frontend

Cyber-derived HUD for the GitHub Capability & Security Sentinel. Read-only over the
existing FastAPI + SQLite backend — no second backend, no simulated data.

Visual reference: `D:\ai-experiments\websites\cyber` (left untouched).

## Run

```bash
npm install
npm run dev        # http://localhost:5173 (proxies /api -> :8000)
npm run build      # tsc --noEmit && vite build
npm run preview    # serves dist on :4173 with the same /api proxy
npm run typecheck
npm test           # vitest
```

The backend runs separately: `python -m uvicorn dashboard.api:app` → `http://localhost:8000`.
The browser only ever calls same-origin `/api/*`; `vite.config.ts` proxies it to the API
and strips the prefix, so the FastAPI routes are untouched.

## Structure

```
src/
  api/          types.ts (v1 contracts), client.ts (fetch + typed errors),
                events.ts (SSE reader over fetch, frame parser),
                legacy.ts (the single v1 -> display mapper)
  components/   Panel (chamfered HUD container, labelled <section>)
  hooks/        useClock (wall clock, isolated from data fetching)
                useResource (abort + stale-response guard for any fetch)
                useDossier (detail fetch through the mapper)
                useLiveEvents (one SSE connection, resume + backoff)
  layout/       Shell (header, section nav, API reachability, main)
  pages/        Overview (system-wide counts), Repository (selection + artifacts)
  state/        url.ts (query-string state, so links are shareable)
  styles/       index.css — Cyber theme tokens + chamfer/CRT utilities
```

View state lives in the URL: `?view=repository&repo=900001` opens the same page after a
reload or from a pasted link.

## Live events

`useLiveEvents` owns one SSE connection (`/api/events/stream`) for the whole app. It reads the
stream with `fetch` rather than `EventSource` because a fresh `EventSource` cannot send the
`last-event-id` header the backend uses to resume. On reconnect it resumes from the last seen
id, drops any event with an id it already has, and keeps the newest 100 in memory.

A result-bearing event (`SYNTHESIS_DONE`, `SECURITY_DONE`, `REPORTED`, `FAILED_AUDIT`, `ERROR`,
`RECLAIMED`) for the open repository refetches that dossier only; progress chatter does not.

If the stream drops, the feed says so and the badge goes `RECONNECTING` → `OFFLINE` with a
manual `RETRY`, while the header's `API:` state is re-checked on every retry. There is no polling
fallback: the backend exposes events only as a stream, and adding a REST replay route would be a
backend change outside this frontend's scope.

## Data honesty rules

- A missing security artifact renders as "missing data, not a clean scan" — never as zero
  findings.
- A present-but-unreadable artifact renders as `invalid`, not as an empty section.
- Malformed findings are dropped **and counted**, never replaced.
- Claims and verified-reality lists stay separate: v1 has no pairing between them.
- Every v1 artifact is labelled `legacy_unverified`; `/health` is used for reachability only
  and its `db` path is never displayed.
- Unknown severities display as `UNKNOWN` with the raw value preserved.

## Deliberate omissions

- No fake telemetry, training curves, confusion matrix, overclock or quantization controls.
- No remote fonts — display/mono faces fall back to system fonts so the HUD works offline.
- Nav items are disabled until their backend resource exists; "SOON" is shown instead of an
  empty page, so no tab implies a capability the API does not have.
- Production code never imports fixtures. Demo data, when needed, goes in `src/fixtures/`
  and is labelled.
