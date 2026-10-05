# End-to-end tests

Playwright specs that exercise the real compose stack: login through Keycloak, the Library
drawer and its dialogs, an analysis page, and Settings. These are not part of `npm test`
(vitest ignores this directory) because they need a running backend, database and Keycloak,
not a mocked one.

## Running

1. Start the stack (project `plan-4-api` or your own compose project name) and make sure the
   frontend is reachable, Keycloak has the `vocal-coach` realm with a `demo`/`demo` user, and
   the backend is reachable through the frontend's `/api` proxy.
2. Install the Chromium browser Playwright drives (once per machine, or after a
   `@playwright/test` upgrade):

   ```bash
   npm run e2e:install
   ```

3. Run the suite:

   ```bash
   npm run e2e
   ```

### Environment variables

- `E2E_BASE_URL`: where the frontend is served. Defaults to `http://localhost:3000`.
- `E2E_USER` / `E2E_PASSWORD`: the demo user's credentials used to sign in. Default to
  `demo` / `demo`.
- `E2E_USER_EMAIL`: the email the Settings test expects to see in the Account section.
  Defaults to `demo@example.test`.

## What it covers

- `library.spec.ts`: the Library page renders, the "Analyse" button opens the drawer
  (Escape closes it), the theme toggle changes its accessible name on click, and a row's
  "Delete" button opens a confirm dialog that Cancel closes.
- `analysis.spec.ts`: opens the first analysis row (skipped with a message if there are no
  rows yet), checks all five tabs are present, switches to Coaching, and then either finds
  the "Re-run coaching" button disabled with its explanatory text, or clicks it and checks the
  "Re-run coaching" dialog opens.
- `settings.spec.ts`: the Account section shows the demo user's email, the Google Drive
  section shows either a "Connect Google Drive" button or the "not configured" note, and
  "Sign out" navigates away to Keycloak or the login page.

Every spec waits for `page.waitForLoadState("networkidle")` after navigating, before clicking
anything. This suite exists in part to catch an intermittent issue where a synthetic click
right after load lands before the page has finished settling.

## Auth

`global-setup.ts` runs once before the suite: it opens a fresh browser context, lets the app
redirect to Keycloak's real login form, signs in as the demo user, waits for the Library page,
and saves the browser's storage state to `e2e/.auth/demo.json` (gitignored).

The app keeps its own OIDC session in `sessionStorage` (see `src/auth/oidc.ts`), and
Playwright's `storageState` does not capture `sessionStorage`. So what actually gets reused
across specs is Keycloak's own SSO session cookie, which `storageState` does persist: every
spec navigates to `baseURL` fresh, the app's route guard immediately redirects to Keycloak,
Keycloak recognizes its own SSO cookie and redirects straight back with a new authorization
code, and the app signs in with no password prompt. If that ever proves unreliable (for
example, a change to Keycloak's SSO cookie attributes), move the sign-in into a
`test.beforeEach` helper in each spec file instead of relying on the saved storage state.
