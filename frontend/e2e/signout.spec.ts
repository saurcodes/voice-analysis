import { expect, test } from "@playwright/test";

/**
 * Signing out ends the Keycloak SSO session that every other spec relies on (they all share
 * the storageState written by global-setup), so this spec lives in its own Playwright project
 * that depends on the main one and therefore runs only after every other test has finished.
 */
test("Sign out leads to Keycloak or the login page", async ({ page }) => {
  await page.goto("/settings");
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: "Sign out" }).first().click();
  await page.waitForLoadState("networkidle");

  const url = page.url();
  expect(url.includes("/login") || /:8080\//.test(url) || /\/realms\//.test(url)).toBe(true);
});
