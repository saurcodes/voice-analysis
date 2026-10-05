import { chromium, type FullConfig } from "@playwright/test";

const AUTH_FILE = "e2e/.auth/demo.json";

/**
 * Signs in once as the demo user through the real Keycloak login form and saves the
 * resulting browser storage so every spec starts already authenticated.
 *
 * The app keeps its OIDC session in sessionStorage (see src/auth/oidc.ts), and Playwright's
 * storageState does not persist sessionStorage. So this does not try to carry the app's own
 * session forward; instead it relies on Keycloak's SSO cookies, which storageState does
 * persist. Each spec then navigates to baseURL fresh: RequireAuth immediately redirects to
 * Keycloak, Keycloak sees its own SSO cookie and redirects straight back with a fresh
 * authorization code, and the app logs in with no password prompt. If Keycloak's SSO
 * session is ever not picked up this way (e.g. a cookie attribute change), move this sign-in
 * into a `test.beforeEach` helper in each spec file instead.
 */
async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL =
    config.projects[0]?.use?.baseURL ?? process.env.E2E_BASE_URL ?? "http://localhost:3000";
  const username = process.env.E2E_USER ?? "demo";
  const password = process.env.E2E_PASSWORD ?? "demo";

  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    await page.goto(baseURL);
    // RequireAuth redirects an unauthenticated visitor straight to Keycloak.
    await page.waitForURL(/\/realms\/.+\/protocol\/openid-connect\/auth/, { timeout: 30_000 });

    await page.getByLabel("Username or email").fill(username);
    await page.getByRole("textbox", { name: "Password" }).fill(password);
    await page.getByRole("button", { name: "Sign In" }).click();

    // Back on the app, authenticated: the Library page is the post-login landing page.
    await page.getByRole("heading", { name: "Library" }).waitFor({ state: "visible", timeout: 30_000 });

    await context.storageState({ path: AUTH_FILE });
  } finally {
    await browser.close();
  }
}

export default globalSetup;
