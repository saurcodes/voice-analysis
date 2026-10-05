# Vocal Coach frontend

Vite + React + TypeScript app: upload recordings, watch job progress live, browse the Library,
read one analysis, compare recordings, manage account settings. Served in production by nginx
(see "Production build and compose service" below).

## Dev loop

```bash
npm install
npm run dev
```

Opens on `http://localhost:5173`. `vite.config.ts` proxies `/api` to `http://localhost:8000`
(the backend, run separately: `docker compose up -d postgres keycloak backend` or the backend's
own `uvicorn --reload` loop, see `backend/README.md`). Keycloak must be reachable at
`http://localhost:8080` (`docker compose up -d keycloak`); sign in with the dev realm's seeded
user, `demo` / `demo`.

## Tests, lint, build

```bash
npm test          # Vitest + React Testing Library + MSW, run once
npm run test:watch
npm run lint       # ESLint
npm run build      # tsc -b && vite build
```

No test hits the network: API calls are mocked through MSW and auth through a test
`AuthProvider`.

## Regenerating API types

`src/api/types.ts` is generated, never hand-edited:

```bash
# from backend/, after any API change:
python scripts/export_openapi.py   # writes backend/openapi.json
# from frontend/:
npm run gen:api                    # openapi-typescript ../backend/openapi.json -> src/api/types.ts
```

## Design tokens and theme

All color, radius and font tokens live in `src/index.css` as CSS variables, redefined per theme
(`prefers-color-scheme` and a manual `data-theme` override persisted in `localStorage`). One
accent only: cobalt, mapped through the `primary` Tailwind utilities (`bg-primary`,
`text-primary`, `ring-primary`). shadcn/ui's own `accent` utilities are repointed to the neutral
hover/selected surface (`--muted`), not the brand color, since shadcn's "accent" conventionally
means a neutral surface and this app already has a semantically distinct brand accent. Do not use
`bg-accent` for a call-to-action; use `bg-primary`.

## Chart colors

Chart series colors are `--chart-1`, `--chart-2`, `--chart-3` in `src/index.css`, in the dataviz
reference categorical palette, fixed slot order, capped at 3 series per chart. Validated with the
dataviz skill's contrast validator:

- Light: `#2a78d6`, `#eb6834`, `#1baf7a`: pass, with a contrast warning on slot 3 against the
  light background; relieved in the UI by always pairing color with a legend and a table view
  (values are never conveyed by color alone).
- Dark: `#3987e5`, `#d95926`, `#199e70`: pass.

Single-series charts use the `primary` accent instead of the chart palette.

## Coaching

The Coaching tab's "Re-run coaching" button only enables once `GET /api/me` reports
`llm_enabled: true`, which mirrors the server's `llm.enabled` setting only; it says nothing about
whether the provider is reachable. Model availability comes from `GET /api/llm/models`, which
feeds the re-run dialog's model list and the upload drawer's LLM switch. When that call fails
(503), both show "Coaching provider is unavailable right now" and keep coaching disabled. Any
number or markup mismatch the backend's post-checks catch is shown under a "Checks" heading
on the coaching output itself, not just in the dialog.

## Google Drive

When the backend reports `drive_configured: true` (via `GET /api/me`), Settings shows a Connect
button for linking the signed-in user's own Google Drive, and the Analyse drawer gains a Drive tab
that lists audio/video files by folder id for picking files to analyse without uploading. Otherwise
both show a "Google Drive is not configured on this server" state instead; once configured but not
yet linked for this user (`drive_connected: false`), Settings shows Connect and the Drive tab shows
a connect prompt instead of a file list.

## SSE client

`src/api/sse.ts` is a fetch-based client (native `EventSource` cannot send an `Authorization`
header, and Keycloak access tokens last 300 seconds, so a long stream needs the client to reuse
its own fetch with a fresh bearer token, not the browser's EventSource). It parses CRLF-delimited
`event:`/`data:` frames from the response stream. On a network error or an explicit `timeout`
event it falls back to polling `GET /api/jobs/{id}` every 2 seconds, so progress keeps moving even
if the stream itself dies mid-job.

## Production build and compose service

```bash
cp .env.example .env   # repo root; edit if needed
docker compose up -d --build
```

Builds `frontend/Dockerfile` (`node:22-alpine` building the Vite bundle, then `nginx:1.27-alpine`
serving `dist/` with the SPA fallback and an `/api/` reverse proxy to the `backend` service) and
starts it as the `frontend` service on port 3000. Open `http://localhost:3000`.

The three `VITE_KEYCLOAK_*` values are build-time only: Vite inlines `import.meta.env.*` into the
static bundle, so there is no runtime config step in the nginx image. Set them in the root `.env`
before building if your Keycloak is not at the compose defaults; changing them after the image is
built needs `docker compose up -d --build frontend` again.

The nginx `/api/` location has `proxy_buffering off`, `proxy_cache off` and a 3600s
`proxy_read_timeout`: `GET /api/jobs/{id}/events` is a long-lived Server-Sent-Events stream and
nginx must forward each chunk as the backend writes it rather than buffering until the response
ends. `client_max_body_size` is 600m, above the backend's default `MAX_UPLOAD_MB=500`.

### Keycloak redirect URIs

Both realm export files allow `http://localhost:5173/*` (Vite dev) and `http://localhost:3000/*`
(nginx) as redirect URIs and web origins. Keycloak imports a realm file only when that realm does
not already exist (`--import-realm` does not re-import into an existing database), so a stack that
was already running before this change keeps its old `post.logout.redirect.uris` value until its
Postgres volume is reset, or until the client is edited by hand in the admin console
(`http://localhost:8080/admin`, `admin` / `admin` per `docker-compose.yml`, realm `vocal-coach`,
client `vocal-coach-web`, Advanced tab): add `http://localhost:3000/*` to
"Valid post logout redirect URIs". Without that edit, sign-in and the app itself work the same
from either port; only the Keycloak-side redirect after signing out from `:3000` fails.
