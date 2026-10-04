# Vocal Coach — Plan 5: React UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every implementer MUST invoke the `design-taste-frontend` skill before writing UI and the `dataviz` skill before writing any chart.

**Goal:** A production-shaped React app in `frontend/` that lets a logged-in user upload recordings, watch job progress live, browse their Library, read one analysis (summary cards, timeline charts, transcript with highlights, raw downloads), compare recordings, and manage account settings; built, tested, served by nginx in the compose stack.

**Design Read (declared, per the taste skill):** *Reading this as: a Linear-style product UI for a speaker reviewing their own recordings, with a calm, data-first language, leaning toward Tailwind v4 + shadcn/ui (owned, customised) + Recharts.* Dials: `DESIGN_VARIANCE 5`, `MOTION_INTENSITY 3`, `VISUAL_DENSITY 5`. This is product UI, not a landing page: one design system, no hero theatrics, full loading/empty/error states, tables for data, charts via the dataviz method.

**Visual contract (locked for the whole app):**
- **Type:** Geist (UI) + Geist Mono (every number, timestamp, metric value). Self-hosted via `@fontsource-variable/geist` and `@fontsource-variable/geist-mono`. No Inter.
- **Color:** zinc neutrals; ONE accent, cobalt `oklch(0.55 0.17 255)` (light) / `oklch(0.72 0.14 255)` (dark). Status colours reserved for verdicts and job states only (good / warning / serious), always paired with an icon + text, never colour alone. No purple, no glows, no pure black/white.
- **Shape:** radius 8px everywhere (`--radius: 0.5rem`); no pill buttons, no sharp cards.
- **Theme:** light/dark from one CSS-variable token set, default `prefers-color-scheme`, manual toggle in the header persisted in `localStorage` as a per-viewer convenience.
- **Icons:** `@phosphor-icons/react`, `weight="regular"`, one family only.
- **Motion:** `motion/react` only for state transitions (drawer open, row enter, progress bar). Honour `prefers-reduced-motion`.
- **Copy:** plain functional labels. Zero em-dashes anywhere. One label per intent: "Analyse" (upload CTA), "Compare", "Delete", "Retry", "Download".
- **Charts (dataviz method):** small multiples, one y-axis per chart, thin 2px lines, ≥8px hover markers, crosshair tooltip, recessive grid; single-series charts use the accent; multi-series (compare trends) use the dataviz reference categorical palette in fixed slot order, capped at 3 series per chart (fold the rest or let the user pick); values rendered in text tokens, never series colour.

**Tech Stack:** Vite 6, React 19, TypeScript, React Router 7, TanStack Query 5, `oidc-client-ts` + `react-oidc-context`, Tailwind v4 (`@tailwindcss/vite`), shadcn/ui (owned components), Recharts 2, `motion/react`, Phosphor icons, `openapi-typescript`, Vitest + React Testing Library + MSW 2; nginx for serving.

**Spec:** `docs/superpowers/specs/2026-10-03-vocal-coach-design.md` §13 (Frontend), §12 (API), §10 (SSE), §14 (compose `frontend` service). Backend facts from Plan 4: typed OpenAPI at `/openapi.json`; SSE needs a fetch-based client (native `EventSource` cannot send `Authorization`; Keycloak access tokens last 300 s); SSE events `stage | progress | done | error | timeout`, not every stage guaranteed; errors are `{"detail": string}` except FastAPI 422 lists; `/me.llm_enabled` is `false` and `/llm/models` returns `enabled: false` until Plan 6; Drive endpoints 501 until Plan 7; `POST /api/analyses/{id}/coach` → 501.

## Global Constraints

- Node ≥ 20 with **npm** (no pnpm on this machine). Frontend lives in `frontend/`; all commands run from there.
- One design system: shadcn/ui components live in `frontend/src/components/ui/` and are customised to the visual contract (radius, tokens, font); never shipped in default state.
- API types are GENERATED: `frontend/src/api/types.ts` from `backend/openapi.json` via `npm run gen:api`; never hand-edited. The backend exports `openapi.json` with `backend/scripts/export_openapi.py` (added in Task 1). Both files are committed.
- All API calls go through `frontend/src/api/client.ts` (adds `Authorization: Bearer`, maps 401 → silent renew then redirect to login, maps `{detail}` to `ApiError`).
- SSE via `frontend/src/api/sse.ts` (fetch + ReadableStream parser); on `timeout`/network error fall back to polling `GET /api/jobs/{id}` every 2 s.
- Every page handles loading (skeleton matching layout), empty, and error states. No spinners-only loading.
- Accessibility: WCAG AA contrast for text and controls in both themes; keyboard-reachable drawer, tabs, table actions; focus rings visible.
- Tests: Vitest + RTL + MSW; no network in tests; auth mocked through a test `AuthProvider`. `npm test` green; `npm run build` green; `npm run lint` green.
- Commit after every task; messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **Access token expires mid-session (300 s)**: the next API call must silently renew and succeed; if renewal fails, redirect to login without losing the current route. Test in Task 2.
2. **SSE stream dies or emits `timeout` while the job is still running**: the UI must keep showing progress via polling, not freeze or show "failed". Test in Task 4.
3. **Analysis with `recording_quality.reasons` = `too_short` or `no_voiced_speech`** (all metric fields null): Summary shows a warning state, no NaN/"null" text, Timeline shows an empty state. Test in Task 5.
4. **Compare with a `partial` row or `analyser_version_mismatch`**: badges/banners visible, arrows still render, no crash on `null` values. Test in Task 6.
5. **Upload of a disallowed or oversized file**: the API's 415/413 `detail` is shown inline in the drawer, other files in the batch still proceed. Test in Task 4.

---

### Task 1: Scaffold, design tokens, generated API types, test harness

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tsconfig.app.json`, `frontend/tsconfig.node.json`, `frontend/index.html`, `frontend/.gitignore`, `frontend/eslint.config.js`, `frontend/components.json` (shadcn), `frontend/.env.example`
- Create: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/lib/utils.ts`, `frontend/src/lib/theme.tsx`, `frontend/src/components/ui/{button,card,badge,tabs,table,dialog,sheet,input,label,textarea,switch,skeleton,tooltip,separator,alert,select}.tsx` (via `npx shadcn@latest add …` then customised)
- Create: `frontend/src/components/AppShell.tsx`
- Create: `backend/scripts/export_openapi.py`, `backend/openapi.json`
- Create: `frontend/src/api/types.ts` (generated)
- Create: `frontend/src/test/setup.ts`, `frontend/src/test/render.tsx`, `frontend/src/test/msw.ts`
- Test: `frontend/src/components/AppShell.test.tsx`

**Interfaces:**
- Produces: `cn()` (clsx + tailwind-merge); `ThemeProvider`, `useTheme() -> {theme: "light"|"dark"|"system", setTheme}` (applies `data-theme` on `<html>`, persists to `localStorage` key `vc-theme` inside try/catch); `AppShell({children})` with header (wordmark "Vocal Coach", nav links Library / Compare / Settings, theme toggle, user menu slot) and `<main>`; test helpers `renderWithProviders(ui, {route?, auth?})` wrapping Router + QueryClient + Theme + a mock auth context (Task 2 fills the real one; Task 1 exports a placeholder `AuthContext` from `src/auth/context.tsx` with `{user, token, signinRedirect, signoutRedirect, renew}`), `server` (MSW node server) started in setup.
- Produces (backend): `backend/scripts/export_openapi.py` writing `backend/openapi.json` from `create_app(...).openapi()` with `require_ffmpeg=False` and a SQLite in-memory engine (no DB connection, no migrations).

- [ ] **Step 1: Scaffold**

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install react-router@7 @tanstack/react-query@5 oidc-client-ts react-oidc-context recharts motion @phosphor-icons/react @fontsource-variable/geist @fontsource-variable/geist-mono clsx tailwind-merge class-variance-authority
npm install -D tailwindcss @tailwindcss/vite openapi-typescript vitest @vitest/coverage-v8 jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom msw@2 @types/node eslint-plugin-react-hooks
npx shadcn@latest init -d
npx shadcn@latest add button card badge tabs table dialog sheet input label textarea switch skeleton tooltip separator alert select
```

`vite.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { port: 5173, proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false },
});
```

`src/index.css` (tokens; the whole app's palette lives here):

```css
@import "tailwindcss";
@import "@fontsource-variable/geist";
@import "@fontsource-variable/geist-mono";

@theme {
  --font-sans: "Geist Variable", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Geist Mono Variable", ui-monospace, SFMono-Regular, monospace;
  --radius: 0.5rem;
}

:root {
  color-scheme: light;
  --background: oklch(0.985 0.002 90);
  --foreground: oklch(0.2 0.01 260);
  --muted: oklch(0.95 0.004 260);
  --muted-foreground: oklch(0.5 0.015 260);
  --card: oklch(1 0 0);
  --border: oklch(0.9 0.006 260);
  --accent: oklch(0.55 0.17 255);          /* cobalt: the only accent */
  --accent-foreground: oklch(0.99 0 0);
  --good: oklch(0.6 0.15 150);             /* status: improved / done */
  --warning: oklch(0.72 0.15 75);          /* status: partial / low confidence */
  --serious: oklch(0.58 0.2 25);           /* status: worsened / failed */
  --chart-1: #2a78d6; --chart-2: #eb6834; --chart-3: #1baf7a;   /* dataviz reference slots 1-3 (light) */
}
:root:not([data-theme="light"]) { @media (prefers-color-scheme: dark) { /* dark values */ } }
:root[data-theme="dark"] { color-scheme: dark; --background: oklch(0.17 0.006 260); --foreground: oklch(0.95 0.005 260); --muted: oklch(0.23 0.006 260); --muted-foreground: oklch(0.68 0.01 260); --card: oklch(0.2 0.006 260); --border: oklch(0.3 0.008 260); --accent: oklch(0.72 0.14 255); --accent-foreground: oklch(0.15 0.01 260); --good: oklch(0.72 0.14 150); --warning: oklch(0.8 0.13 80); --serious: oklch(0.7 0.17 25); --chart-1: #3987e5; --chart-2: #d95926; --chart-3: #199e70; }

body { @apply bg-[var(--background)] text-[var(--foreground)] font-sans antialiased; }
.num { @apply font-mono tabular-nums; }
```

Write the dark block once as a CSS variable set and reuse it in both the media query (guarded by `:root:not([data-theme="light"])`) and the `[data-theme="dark"]` selector (duplicate the declarations; do not rely on nesting support).

`src/lib/theme.tsx`: `ThemeProvider` reads `localStorage.getItem("vc-theme")` in try/catch, sets `document.documentElement.dataset.theme` to `"light"|"dark"` or removes it for `"system"`.

`components.json`: `"style": "new-york"`, `"tailwind": {"css": "src/index.css", "baseColor": "zinc", "cssVariables": true}`, aliases `@/components`, `@/lib/utils`. After `shadcn add`, edit the generated components: radius from `--radius`, remove any `rounded-full` on buttons (use `rounded-md`), font from tokens, focus ring `ring-[var(--accent)]`.

`src/components/AppShell.tsx`: header `h-14` with wordmark (text, `font-semibold tracking-tight`), nav (`Library`, `Compare`, `Settings`) using `NavLink` with `aria-current`, theme toggle (Phosphor `Sun`/`Moon`/`Monitor` cycling system→light→dark, labelled), `UserMenu` slot (Task 2), `<main className="mx-auto max-w-7xl px-4 py-8">`.

`backend/scripts/export_openapi.py`:

```python
"""Write backend/openapi.json from the app factory without touching a database."""
from __future__ import annotations

import json
from pathlib import Path

from vocal_coach.config import load_config
from vocal_coach.jobs.runner import JobRunner, SyncExecutor
from vocal_coach.main import create_app
from vocal_coach.settings import Settings
from vocal_coach.storage.db import make_engine

OUT = Path(__file__).resolve().parents[1] / "openapi.json"

settings = Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:", require_ffmpeg=False)
cfg = load_config()
app = create_app(settings, cfg, engine=make_engine(settings.database_url),
                 runner=JobRunner(settings, cfg, executor=SyncExecutor()), run_migrations=False)
OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {OUT}")
```

`package.json` scripts: `"dev": "vite"`, `"build": "tsc -b && vite build"`, `"preview": "vite preview"`, `"test": "vitest run"`, `"test:watch": "vitest"`, `"lint": "eslint ."`, `"gen:api": "openapi-typescript ../backend/openapi.json -o src/api/types.ts"`.

Test harness: `src/test/setup.ts` imports `@testing-library/jest-dom/vitest`, starts `server` (`msw/node`) `beforeAll`, `afterEach(server.resetHandlers)`, `afterAll(server.close)`; polyfill `window.matchMedia`. `src/test/msw.ts` exports `server = setupServer()` and `handlers.ts` base handlers for `/api/me`, `/api/config/public`, `/api/llm/models` (filled in Task 3). `src/test/render.tsx` exports `renderWithProviders`.

- [ ] **Step 2: Failing test**

`src/components/AppShell.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { AppShell } from "./AppShell";

test("renders nav and toggles theme", async () => {
  renderWithProviders(<AppShell><p>content</p></AppShell>);
  expect(screen.getByRole("link", { name: "Library" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Compare" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  expect(screen.getByText("content")).toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: /theme/i });
  await userEvent.click(toggle);
  expect(["light", "dark", undefined]).toContain(document.documentElement.dataset.theme);
});
```

- [ ] **Step 3: Run, implement, run**

`npm test` → fails (missing modules) → implement → passes. `npm run build` and `npm run lint` pass. Generate types: from `backend/`: `.venv/bin/python scripts/export_openapi.py`; from `frontend/`: `npm run gen:api`; confirm `src/api/types.ts` contains `AnalysisSummary`, `JobStatus`, `ComparisonResult`, `MetricsReport`.

- [ ] **Step 4: Commit**

```bash
git add frontend backend/scripts/export_openapi.py backend/openapi.json
git commit -m "feat(frontend): Vite + React scaffold, design tokens, shadcn components, generated API types, test harness

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Auth (Keycloak OIDC), API client, Login and Settings pages

**Files:**
- Create: `frontend/src/auth/oidc.ts`, `frontend/src/auth/context.tsx` (replace placeholder), `frontend/src/auth/RequireAuth.tsx`, `frontend/src/auth/UserMenu.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/SettingsPage.tsx`
- Modify: `frontend/src/App.tsx` (routes), `frontend/src/components/AppShell.tsx` (mount `UserMenu`)
- Test: `frontend/src/api/client.test.ts`, `frontend/src/auth/RequireAuth.test.tsx`, `frontend/src/pages/SettingsPage.test.tsx`

**Interfaces:**
- `oidc.ts`: `oidcConfig` from `import.meta.env.VITE_KEYCLOAK_URL` (default `http://localhost:8080`), `VITE_KEYCLOAK_REALM` (`vocal-coach`), `VITE_KEYCLOAK_CLIENT_ID` (`vocal-coach-web`): `{authority: `${url}/realms/${realm}`, client_id, redirect_uri: window.location.origin + "/", post_logout_redirect_uri: origin + "/login", response_type: "code", scope: "openid profile email", automaticSilentRenew: true, userStore: new WebStorageStateStore({store: window.sessionStorage}), onSigninCallback: () => history.replaceState({}, "", location.pathname)}`.
- `context.tsx`: `AuthProvider` wraps `react-oidc-context`'s `AuthProvider` and exposes `useAuthState() -> {isAuthenticated, isLoading, user: {name, email} | null, getToken(): Promise<string>, signin(returnTo?), signout()}`. `getToken()` returns the current access token, calling `signinSilent()` first if it expires within `TOKEN_SKEW_S = 20`.
- `client.ts`: `class ApiError extends Error {status: number; detail: string | unknown}`; `apiFetch<T>(path, init?, {getToken}) -> Promise<T>`; on 401 once: `await renew()` then retry; if still 401 → `onUnauthorized()` (redirect to `/login?returnTo=<route>`); non-2xx → `ApiError` with `detail` from body (`{detail}` or 422 list joined). `createApi(getToken, onUnauthorized)` returns bound `get/post/postForm/del` helpers. Also `downloadUrl(path)` helper and `authFetch(path, init)` for streaming (SSE, downloads).
- `RequireAuth`: renders children if authenticated; while loading shows a full-page skeleton; else `signin(currentPath)`.
- `LoginPage`: single button "Sign in with Keycloak"; if `?returnTo=` present and already authenticated → navigate there.
- `SettingsPage`: account block (name, email), "Google Drive" block with a disabled `Connect Google Drive` button and the text "Available in a later release", "Sign out" button.

- [ ] **Step 1: Failing tests**

`src/api/client.test.ts`:

```ts
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw";
import { createApi, ApiError } from "./client";

test("adds bearer and parses json", async () => {
  server.use(http.get("/api/me", ({ request }) => {
    expect(request.headers.get("authorization")).toBe("Bearer t1");
    return HttpResponse.json({ id: "u", username: "demo" });
  }));
  const api = createApi(async () => "t1", () => {});
  await expect(api.get("/api/me")).resolves.toMatchObject({ username: "demo" });
});

test("401 renews once then retries; second 401 calls onUnauthorized", async () => {
  let calls = 0;
  server.use(http.get("/api/me", () => (++calls === 1 ? new HttpResponse(null, { status: 401 }) : HttpResponse.json({ id: "u" }))));
  const tokens = ["old", "new"];
  const api = createApi(async () => tokens.shift() ?? "new", () => {});
  await expect(api.get("/api/me")).resolves.toMatchObject({ id: "u" });
  expect(calls).toBe(2);

  const onUnauthorized = vi.fn();
  server.use(http.get("/api/me", () => new HttpResponse(null, { status: 401 })));
  await expect(createApi(async () => "x", onUnauthorized).get("/api/me")).rejects.toBeInstanceOf(ApiError);
  expect(onUnauthorized).toHaveBeenCalled();
});

test("maps detail and 422 lists to ApiError", async () => {
  server.use(http.get("/api/x", () => HttpResponse.json({ detail: "nope" }, { status: 415 })));
  await expect(createApi(async () => "t", () => {}).get("/api/x")).rejects.toMatchObject({ status: 415, detail: "nope" });
  server.use(http.get("/api/y", () => HttpResponse.json({ detail: [{ loc: ["query", "limit"], msg: "too small" }] }, { status: 422 })));
  await expect(createApi(async () => "t", () => {}).get("/api/y")).rejects.toMatchObject({ status: 422, detail: "limit: too small" });
});
```

`src/auth/RequireAuth.test.tsx`: unauthenticated → `signin` called with the current path; authenticated → children render; loading → skeleton has `aria-busy`.

`src/pages/SettingsPage.test.tsx`: shows name/email from mock auth, Drive button disabled with the "later release" text, sign out calls `signout`.

- [ ] **Step 2: Implement; run tests, build, lint; commit**

```bash
git add frontend
git commit -m "feat(frontend): Keycloak OIDC auth, API client with silent renew, Login and Settings pages

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Typed API hooks, SSE client, MSW fixtures

**Files:**
- Create: `frontend/src/api/hooks.ts`, `frontend/src/api/sse.ts`, `frontend/src/api/upload.ts`
- Create: `frontend/src/test/fixtures.ts`, `frontend/src/test/handlers.ts`
- Test: `frontend/src/api/sse.test.ts`, `frontend/src/api/upload.test.ts`, `frontend/src/api/hooks.test.tsx`

**Interfaces:**
- `hooks.ts` (TanStack Query, all typed from `types.ts` via `components["schemas"][...]`): `useMe()`, `usePublicConfig()`, `useLlmModels()`, `useSummaries({limit, offset})`, `useJobs({status?})` (refetch every 5 s while any job is `queued|running`), `useJob(id, {enabled})`, `useAnalysis(id)`, `useComparison(ids: string[])`, `useDeleteAnalysis()` (invalidates summaries), `useRetryJob()`; query keys under `["vc", ...]`.
- `upload.ts`: `uploadAnalysis(file: File, fields: {speaker_context?, llm_enabled?, llm_model?, recorded_at?}, {getToken, onProgress(pct)}) -> Promise<{job_ids: string[]}>` using `XMLHttpRequest` for upload progress; maps non-2xx to `ApiError` like the client; `recorded_at` defaults to `new Date(file.lastModified).toISOString()`.
- `sse.ts`: `type JobEvent = {event: "stage"|"progress"|"done"|"error"|"timeout"; data: Record<string, unknown>}`; `streamJobEvents(jobId, {authFetch, signal, onEvent}) -> Promise<"done"|"error"|"timeout"|"aborted"|"disconnected">` parsing `text/event-stream` frames (`event:`/`data:` lines, blank-line delimited) from `response.body.getReader()`; `watchJob(jobId, deps, onStatus)` orchestrates: SSE first; on `timeout` or `disconnected` fall back to polling `GET /api/jobs/{id}` every `POLL_MS = 2000` until terminal; returns an `abort()`.
- Fixtures: `summary()`, `jobStatus()`, `analysisDetail()` (a realistic `MetricsReport` + `Transcript` built once as JSON — copy the shape from `backend/openapi.json` and the real smoke output: 1 recording with 3 phrases, 15 s windows, a `too_short` variant, and a `no_voiced_speech` variant), `comparison()` with one `partial` row and `analyser_version_mismatch: true`; `handlers.ts` MSW handlers for every endpoint used.

- [ ] **Step 1: Failing tests**

`sse.test.ts`: build a `ReadableStream` that emits `event: stage\ndata: {"stage":"extract","progress_pct":20}\n\nevent: done\ndata: {"analysis_id":"a1"}\n\n` → `onEvent` called twice in order, resolves `"done"`; a stream that emits `event: timeout` → `watchJob` switches to polling (MSW `GET /api/jobs/:id` returns `running` then `done`) and reports `done`; a stream whose reader throws mid-way → `"disconnected"` → polling → `done`.

`upload.test.ts`: mock `XMLHttpRequest` (minimal fake) → progress events forwarded; 413 `{detail}` → `ApiError`; `recorded_at` defaults from `lastModified`.

`hooks.test.tsx`: `useSummaries` returns fixtures; `useJobs` sets `refetchInterval` only while a job is active (assert via query state after fake timers advance).

- [ ] **Step 2: Implement; run tests; commit**

```bash
git add frontend
git commit -m "feat(frontend): typed API hooks, upload with progress, SSE client with polling fallback, MSW fixtures

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Library page, Analyse drawer, job progress

**Files:**
- Create: `frontend/src/pages/LibraryPage.tsx`
- Create: `frontend/src/components/library/{AnalysesTable,JobsPanel,AnalyseDrawer,UploadDropzone,JobProgressList,EmptyLibrary}.tsx`
- Modify: `frontend/src/App.tsx` (route `/`)
- Test: `frontend/src/pages/LibraryPage.test.tsx`, `frontend/src/components/library/AnalyseDrawer.test.tsx`, `frontend/src/components/library/JobProgressList.test.tsx`

**Interfaces / behaviour:**
- `LibraryPage`: header row with title "Library", `Analyse` button (primary), `Compare` button (enabled when ≥ 2 rows selected; navigates to `/compare?ids=a,b`). Below: `JobsPanel` (only if any `queued|running|failed` jobs: rows with file name, status badge with icon, progress bar for running, error text and `Retry` for failed), then `AnalysesTable`.
- `AnalysesTable`: columns: select checkbox, File, Recorded (relative + exact on hover, `num`), Pitch range (st), Flat endings %, Pauses/min, Fillers/min, Transcript (badge), Coaching (badge), actions (open, delete with confirm dialog). Sorted by `recorded_at` desc (server order). Numbers in `.num`; `null` renders as a muted "–" (hyphen, not em-dash) with `aria-label="not available"`. Pagination: "Load more" (offset += 50). Loading: skeleton rows; empty: `EmptyLibrary` with the Analyse CTA and one sentence.
- `AnalyseDrawer` (shadcn `Sheet` from the right): tabs `Upload` | `Google Drive` (disabled, tooltip "Available in a later release"); `UploadDropzone` (drag/drop + file picker, multi, accepts `.m4a,.mp3,.wav,.mov,.mp4`, shows size, rejects others client-side with inline text), `speaker_context` textarea (label above, helper text "e.g. real estate sales pitch"), LLM section: switch disabled when `me.llm_enabled === false` with text "Coaching is not enabled on this server yet"; submit button `Analyse N files`. On submit: upload files sequentially, each creating a `JobProgressList` row; per-file errors (413/415) shown inline on that row; the drawer stays open while uploads run, then shows "Done" with links.
- `JobProgressList`: for each job uses `watchJob`; shows stage label (human: "Downloading", "Extracting audio", "Analysing voice", "Transcribing", "Coaching", "Done"), a progress bar (Motion width transition, reduced-motion aware), on `done` a link "Open analysis", on `error` the message + `Retry`. Not every stage event is guaranteed: derive the label from the latest `stage`/`progress`.

- [ ] **Step 1: Failing tests**

`LibraryPage.test.tsx`: renders fixtures (two rows, numbers formatted to 1 decimal in mono), empty state when none, delete flow (confirm → DELETE called → row gone), compare button disabled until two selected then navigates to `/compare?ids=…`, failed job row shows Retry which POSTs retry.

`AnalyseDrawer.test.tsx`: drop two files (one `.txt` rejected client-side with text "Unsupported file type"), fill context, submit → two uploads (MSW counts), progress rows appear; a 413 from MSW for the second file shows its `detail` inline and the first still reaches done; LLM switch disabled with the explanatory text when `llm_enabled` false.

`JobProgressList.test.tsx`: with `watchJob` mocked to emit `stage`/`progress` then `done` → label sequence and link; `error` → message + Retry; `timeout` → still updating from polling (mock reports `running` 55 then `done`).

- [ ] **Step 2: Implement (invoke `design-taste-frontend` first); tests, build, lint; commit**

```bash
git add frontend
git commit -m "feat(frontend): Library page with analyses table, jobs panel, Analyse drawer and live job progress

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Analysis page (Summary, Timeline, Transcript, Coaching, Raw)

**Files:**
- Create: `frontend/src/pages/AnalysisPage.tsx`
- Create: `frontend/src/components/analysis/{SummaryCards,MetricCard,QualityBanner,TimelineCharts,TranscriptView,CoachingPanel,RawPanel}.tsx`
- Create: `frontend/src/lib/metrics.ts` (formatting + label maps + transcript highlighting)
- Modify: `frontend/src/App.tsx` (route `/analyses/:id`)
- Test: `frontend/src/pages/AnalysisPage.test.tsx`, `frontend/src/lib/metrics.test.ts`, `frontend/src/components/analysis/TranscriptView.test.tsx`

**Interfaces / behaviour:**
- `metrics.ts`: `fmt(value: number | null, digits=1) -> string` ("–" for null); `METRIC_LABELS` (path → human label + unit + one-line meaning); `highlightTranscript(transcript, metrics) -> Token[]` where `Token = {kind: "word"|"pause", text, start_s, flags: Set<"filler"|"eaten"|"lowconf">, duration_s?}` — inserts `pause` tokens for `metrics.phrasing.long_pauses` (≥ 1 s) between words whose times bracket the pause, marks fillers by normalised token match against `transcript.derived.filler_counts` keys (multi-word fillers mark both words), eaten from `derived.clarity.eaten_words` (match by `start_s`), low-confidence from `low_conf_words`.
- `SummaryCards`: 8 `MetricCard`s: Median pitch (Hz), Pitch range (st), Flat endings (%), Pauses/min, Articulation rate (syl/s), Trailing off (count), Fillers/min, Eaten words (fraction as %). Each card: label, big `num` value, unit, one-line meaning, `LowConfidence` badge (warning colour + Phosphor `Warning` icon + text "low confidence") when the block's `low_confidence` is true. `QualityBanner` when `recording_quality.reasons` non-empty: maps `too_short` → "Recording shorter than 2 seconds; no metrics computed.", `no_voiced_speech` → "No voiced speech detected.", `low_snr`/`high_noise_floor` → "Noisy recording; voice-quality and articulation metrics are low confidence." Cards show "–" when null.
- `TimelineCharts` (invoke `dataviz` first): three small multiples stacked, each its own y-axis: F0 median (Hz), F0 variation (st), Intensity (dB) per 15 s window; x = window start (mm:ss); 2px accent line, ≥8px hover marker, crosshair tooltip with window range and value in `num`; null windows leave gaps (`connectNulls={false}`); recessive grid; `aria-label` on each chart; a table view toggle ("Show as table") rendering the same windows. Empty state when `windows` empty or all F0 null.
- `TranscriptView`: paragraph flow of tokens; `[pause 1.4s]` as a muted mono chip; fillers underlined with accent, eaten words with warning background, low-confidence with dotted underline; legend row above (icon + label each); when `transcript` is null → empty state "No transcript for this recording."
- `CoachingPanel`: if `coaching` null → unavailable state: "Coaching is not available yet." plus any `coaching_warnings` as a list; when present (Plan 6) render `what_improved`, `what_is_lacking`, `next_steps` lists and `marked_up_example` in a `pre.num`. A disabled "Re-run coaching" button with the server-side reason.
- `RawPanel`: three rows (Metrics, Transcript, Coaching) with `Download` buttons calling `authFetch("/api/analyses/{id}/raw/{kind}")` → blob → anchor download with the server filename from `Content-Disposition`; disabled with "not available" when null.
- Page header: file name, recorded date, analyser version + config hash (short, mono), Delete action; tabs `Summary | Timeline | Transcript | Coaching | Raw`.

- [ ] **Step 1: Failing tests**

`metrics.test.ts`: `fmt(null) === "–"`, `fmt(12.345) === "12.3"`; `highlightTranscript` inserts a pause token between the right words, marks "you know" both words as filler, marks eaten/low-conf by start time.

`TranscriptView.test.tsx`: renders chips and highlighted words with accessible labels (e.g. `aria-label="filler word: so"`); null transcript → empty state.

`AnalysisPage.test.tsx`: full fixture → 8 cards with formatted values and one low-confidence badge; `too_short` fixture → banner text and all cards "–" and Timeline empty state; tab switching; Raw download button triggers fetch to `/raw/metrics`; Coaching unavailable state shows warnings list.

- [ ] **Step 2: Implement (invoke `design-taste-frontend` and `dataviz` first; run `node <dataviz>/scripts/validate_palette.js "#2a78d6" --mode light` is trivial for one series — record that single-series charts use the accent); tests, build, lint; commit**

```bash
git add frontend
git commit -m "feat(frontend): Analysis page with summary cards, timeline charts, transcript highlights, coaching and raw panels

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Compare page

**Files:**
- Create: `frontend/src/pages/ComparePage.tsx`
- Create: `frontend/src/components/compare/{ComparisonTable,TrendCharts,PathPicker,MismatchBanners}.tsx`
- Modify: `frontend/src/App.tsx` (route `/compare`)
- Test: `frontend/src/pages/ComparePage.test.tsx`, `frontend/src/components/compare/ComparisonTable.test.tsx`

**Interfaces / behaviour:**
- `ComparePage`: reads `ids` from the query string; < 2 ids → instruction state with a link back to Library; loads `useComparison(ids)`; header lists the recordings (file names from summaries where available, else short ids) in slot order with their colour swatch (slots 1–3) and date.
- `MismatchBanners`: `config_mismatch` → "These recordings were analysed with different settings; deltas may not be comparable." `analyser_version_mismatch` → "Different analyser versions; numbers may differ for reasons other than your speaking." (warning colour, icon).
- `ComparisonTable`: one row per path in config order; columns: Metric (label + unit from `METRIC_LABELS`), one value column per recording (`num`, "–" for null), Change (delta with arrow glyph `↑ ↓ →` and the verdict as text + icon: `improved` good, `worsened` serious, `unchanged`/`neutral` muted, `unavailable` muted "n/a"), `partial` → small warning badge "gaps" with tooltip "Some recordings lack this metric; change computed from the available ones." Group rows by section (Pitch, Phrasing, Intonation, Energy, Articulation, Transcript) with a subtle group header; no border on every row.
- `TrendCharts` (dataviz): `PathPicker` chips (default 4: `pitch.f0_range_st`, `intonation.flat_pct`, `phrasing.pauses_per_min`, `transcript.derived.fillers_per_min`); one small chart per picked path, x = recorded date, one series per recording **capped at 3** (if more than 3 recordings, show the 3 most recent and a note "showing the 3 most recent"); fixed slot colours; legend present; 2px lines, 8px markers, tooltip; null points gap; table toggle.

- [ ] **Step 1: Failing tests**

`ComparisonTable.test.tsx`: fixture rows render verdict text + arrow, `unavailable` row shows "n/a" and no arrow, `partial` row shows the "gaps" badge; values formatted in mono.

`ComparePage.test.tsx`: `?ids=a` → instruction state; `?ids=a,b` → banners for both mismatches from the fixture, table rows grouped, default 4 charts rendered (`role="img"` with aria-labels), picking another path adds a chart; API 404 → error state "One of these recordings was not found."

- [ ] **Step 2: Implement (invoke `design-taste-frontend` and `dataviz`; run the dataviz validator on the three categorical slots in both modes and paste the pass lines in the report); tests, build, lint; commit**

```bash
git add frontend
git commit -m "feat(frontend): Compare page with verdict table, mismatch banners and trend charts

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Production build, nginx, compose `frontend` service, README

**Files:**
- Create: `frontend/Dockerfile`, `frontend/nginx.conf`, `frontend/.dockerignore`
- Modify: `docker-compose.yml` (add `frontend` on port 3000; backend `FRONTEND_ORIGIN` default `http://localhost:3000` when served by nginx; keep `5173` for Vite dev), `.env.example` (`VITE_*` keys), `backend/README.md` or new `frontend/README.md`
- Test: `npm run build` artefact size check; compose smoke by the controller.

**Behaviour:**
- `Dockerfile`: multi-stage `node:20-alpine` build (`npm ci && npm run build`) → `nginx:1.27-alpine` serving `/usr/share/nginx/html` with `try_files $uri /index.html` and `location /api/ { proxy_pass http://backend:8000; proxy_buffering off; proxy_read_timeout 3600s; }` (buffering off is required for SSE).
- Build-time env: `VITE_KEYCLOAK_URL`, `VITE_KEYCLOAK_REALM`, `VITE_KEYCLOAK_CLIENT_ID` passed as `ARG`s with defaults for the compose stack.
- Keycloak realm files already allow `http://localhost:3000/*` redirect and web origin.
- README (`frontend/README.md`): dev loop (`npm run dev` with Vite proxy to :8000; Keycloak at :8080), tests, `gen:api` after backend changes, theme tokens location, where charts' palette lives, the SSE client note, and the compose service.

- [ ] **Step 1: Files; `docker compose up -d --build frontend`; open `http://localhost:3000`, sign in as demo/demo, upload a WAV, watch progress, open the analysis, compare two. Record what you saw (numbers only).**

- [ ] **Step 2: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore frontend/README.md docker-compose.yml .env.example
git commit -m "feat(deploy): frontend image served by nginx with /api proxy; compose service; README

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage (§13):** stack ✓ (React 19 instead of 18: current Vite template; nothing in the spec depends on 18); pages `/login`, `/` Library with drawer + progress, `/analyses/:id` five tabs, `/compare`, `/settings` ✓. Drive browser tab present but disabled until Plan 7; LLM toggle present but disabled until Plan 6 (server says `llm_enabled: false`); Coaching tab renders the Plan 6 shape when present and an unavailable state now. §14 `frontend` nginx service ✓. OpenAPI → `openapi-typescript` ✓ (committed `backend/openapi.json` + `src/api/types.ts`).
- **Taste-skill conformance:** design read declared; dials set; one system (shadcn/ui + Tailwind v4); Geist not Inter; single accent; status colours only with icon + text; radius lock; theme lock with manual toggle; no em-dashes (null renders as a hyphen); loading/empty/error states per page; icons from Phosphor only; motion minimal and reduced-motion aware; no fake screenshots (the app IS the UI).
- **Dataviz conformance:** one axis per chart, small multiples, fixed categorical slots (reference palette 1–3), series cap 3, legends for ≥ 2 series, text in text tokens, table toggles, hover layer, validator run in Task 6.
- **Type consistency:** `createApi`/`authFetch`/`ApiError` (T2) → hooks/upload/sse (T3) → pages (T4–6); `watchJob` (T3) → `JobProgressList` (T4); `METRIC_LABELS`/`fmt` (T5) → `ComparisonTable` (T6); fixtures/handlers (T3) → all page tests.
- **Review Focus pins:** 1 → `client.test.ts` 401 renew (T2); 2 → `sse.test.ts` timeout/disconnect → polling and `JobProgressList.test.tsx` (T3/T4); 3 → `AnalysisPage.test.tsx` `too_short` fixture (T5); 4 → `ComparisonTable.test.tsx` partial + `ComparePage.test.tsx` banners (T6); 5 → `AnalyseDrawer.test.tsx` 413 inline (T4).
- **Known limits recorded:** no Playwright e2e in this plan (the controller verifies the compose stack in a real browser during the final review); Drive and LLM UI are intentionally disabled shells for Plans 6–7.
