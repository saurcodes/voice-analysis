import { expect, test } from "@playwright/test";

const DEMO_EMAIL = process.env.E2E_USER_EMAIL ?? "demo@example.test";

test.describe("Settings", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/settings");
    await page.waitForLoadState("networkidle");
  });

  test("shows the Account section with the demo email", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();
    await expect(page.getByText(DEMO_EMAIL)).toBeVisible();
  });

  test("shows the Google Drive section with a connect action or a not-configured note", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Google Drive" })).toBeVisible();

    const connectButton = page.getByRole("button", { name: "Connect Google Drive" });
    const notConfigured = page.getByText("Google Drive is not configured on this server");

    const hasConnect = (await connectButton.count()) > 0;
    if (hasConnect) {
      await expect(connectButton).toBeVisible();
    } else {
      await expect(notConfigured).toBeVisible();
    }
  });

  test("Sign out leads to Keycloak or the login page", async ({ page }) => {
    await page.getByRole("button", { name: "Sign out" }).first().click();
    await page.waitForLoadState("networkidle");

    const url = page.url();
    expect(url.includes("/login") || /:8080\//.test(url) || /\/realms\//.test(url)).toBe(true);
  });
});
