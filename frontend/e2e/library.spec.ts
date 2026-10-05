import { expect, test } from "@playwright/test";

test.describe("Library", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    // The app re-authenticates through Keycloak's SSO cookie on load; wait for that round
    // trip and the first data fetch to settle before clicking anything (synthetic clicks
    // right after load have been seen to land before React has attached its handlers).
    await page.waitForLoadState("networkidle");
  });

  test("renders the Library heading", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();
  });

  test("Analyse opens the drawer, and Escape closes it", async ({ page }) => {
    await page.getByRole("button", { name: "Analyse", exact: true }).click();

    const drawer = page.getByRole("dialog", { name: "Analyse recordings" });
    await expect(drawer).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(drawer).not.toBeVisible();
  });

  test("the theme toggle changes its accessible name after a click", async ({ page }) => {
    const toggle = page.getByRole("button", { name: /^Theme: / });
    const before = await toggle.getAttribute("aria-label");
    await toggle.click();
    await expect(toggle).not.toHaveAttribute("aria-label", before ?? "");
  });

  test("a row's Delete button opens a confirm dialog, and Cancel closes it", async ({ page }) => {
    const deleteButton = page.getByRole("button", { name: /^Delete / }).first();
    const rowCount = await deleteButton.count();
    test.skip(rowCount === 0, "no analysis rows to delete");

    await deleteButton.click();

    const dialog = page.getByRole("dialog", { name: "Delete this analysis?" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("Delete this analysis")).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).not.toBeVisible();
  });
});
