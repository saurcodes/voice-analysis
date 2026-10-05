import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright suite that exercises the compose stack end to end (login through Keycloak,
 * the Library drawer and dialogs, and Settings). This is a separate `npm run e2e` command,
 * not part of `npm test`: it needs the stack running at E2E_BASE_URL (default
 * http://localhost:3000) with a demo user (E2E_USER/E2E_PASSWORD, default demo/demo).
 *
 * Auth: globalSetup signs in once through the real Keycloak form and saves the resulting
 * storageState (cookies only; the app keeps its own OIDC session in sessionStorage, which
 * storageState does not capture). Each spec then navigates to baseURL fresh: Keycloak's SSO
 * cookie silently re-authenticates the app without a password prompt.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    storageState: "e2e/.auth/demo.json",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: /signout\.spec\.ts/,
    },
    {
      // Sign out ends the shared Keycloak SSO session, so it runs after everything else.
      name: "signout",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /signout\.spec\.ts/,
      dependencies: ["chromium"],
    },
  ],
});
