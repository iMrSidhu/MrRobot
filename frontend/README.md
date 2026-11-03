# Sentinel frontend

Cyber-derived HUD for the GitHub Capability & Security Sentinel. Read-only over the
existing FastAPI + SQLite backend — no second backend, no simulated data.

Visual reference: `D:\ai-experiments\websites\cyber` (left untouched).

## Run

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc --noEmit && vite build
npm run typecheck
```

The backend runs separately: `python -m uvicorn dashboard.api:app` → `http://localhost:8000`.

## Structure

```
src/
  components/   Panel (chamfered HUD container, labelled <section>)
  hooks/        useClock (wall clock, isolated from data fetching)
  layout/       Shell (header, section nav, main)
  pages/        Overview (placeholder until the API slice lands)
  styles/       index.css — Cyber theme tokens + chamfer/CRT utilities
```

## Deliberate omissions

- No fake telemetry, training curves, confusion matrix, overclock or quantization controls.
- No remote fonts — display/mono faces fall back to system fonts so the HUD works offline.
- Nav items are disabled until their backend resource exists; "SOON" is shown instead of an
  empty page, so no tab implies a capability the API does not have.
- Production code never imports fixtures. Demo data, when needed, goes in `src/fixtures/`
  and is labelled.
