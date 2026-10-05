import { expect, test } from "@playwright/test";

const TABS = ["Summary", "Timeline", "Transcript", "Coaching", "Raw"];

test("open an analysis, switch tabs, and either re-run or see why not", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  const openLink = page.getByRole("link", { name: /^Open / }).first();
  const rowCount = await openLink.count();
  test.skip(rowCount === 0, "no analysis rows exist to open");

  await openLink.click();
  await page.waitForLoadState("networkidle");

  for (const name of TABS) {
    await expect(page.getByRole("tab", { name })).toBeVisible();
  }

  await page.getByRole("tab", { name: "Coaching" }).click();

  const rerunButton = page.getByRole("button", { name: "Re-run coaching" });
  await expect(rerunButton).toBeVisible();

  if (await rerunButton.isDisabled()) {
    await expect(page.getByText("Coaching is not enabled on this server yet")).toBeVisible();
    return;
  }

  await rerunButton.click();
  await expect(page.getByRole("dialog", { name: "Re-run coaching" })).toBeVisible();
});
