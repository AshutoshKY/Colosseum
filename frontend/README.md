# Colosseum frontend

React + TypeScript client for the Colosseum v2 API.

## Development

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8100` (override with `VITE_API_URL`). Start the backend from `backend/`:

```bash
uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8100
```

For a real smoke test, upload two PDFs in **Datasets**, build an OPD run with `segregation`
and `gemini-2.5-flash-lite`, confirm the dry-run check, then launch. The live view uses SSE
and automatically switches to 3-second HTTP polling after a disconnect.

Commands: `npm run build`, `npm run lint`, `npm test`.

## Production

`Dockerfile` is a multi-stage build: the Vite bundle is served by nginx, which also
proxies `/api` (including the SSE stream) to the backend, so the app is same-origin
and needs no CORS setup. `docker compose up frontend` exposes it on port 5173.

- `BACKEND_URL` (container env) — upstream API, defaults to `http://backend:8100`.
- `VITE_API_BASE` (build-time env) — set only if the SPA should call a remote API
  directly instead of the nginx proxy.
- `Dockerfile.dev` runs the hot-reloading dev server instead, for containerised development.

## Structure

- `src/pages/` — one component per route (builder, runs, live view, results, datasets, prompts, catalog, settings).
- `src/components/` — shared UI (document picker, model picker, JSON diff viewer, menus, cards…).
- `src/api/` — fetch client, React Query hooks, SSE subscription, auth token store.
- `src/context/` — run builder draft state; compression/concurrency/judge values persist to
  localStorage as the user's run defaults (edited on the Settings page).
- `src/theme.ts` — light/dark/system theme with localStorage persistence.
- `src/styles.css` — the design system: tokens at the top define both themes.

## Multi-user / auth readiness

There is no login yet, but the plumbing is in place (`src/api/auth.ts`): every request
attaches `Authorization: Bearer <token>` when a token is stored, and a 401 clears it and
emits a `colosseum:unauthorized` event on `window`. To add auth later, build a login flow
that calls `setToken()` and listen for that event to redirect to it. Per-user state
(theme, run defaults) is already scoped to the browser via localStorage.
