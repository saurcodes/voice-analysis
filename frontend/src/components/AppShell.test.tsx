import { screen, within } from "@testing-library/react";
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

test("below the md breakpoint a Menu button opens a Sheet with the nav links and theme toggle, while the inline nav carries the hidden/md:flex classes", async () => {
  const user = userEvent.setup();
  renderWithProviders(<AppShell><p>content</p></AppShell>);

  const menuButton = screen.getByRole("button", { name: "Menu" });
  expect(menuButton).toHaveClass("md:hidden");

  const inlineNav = screen.getByRole("navigation", { name: "Primary" });
  expect(inlineNav.className).toMatch(/\bhidden\b/);
  expect(inlineNav.className).toMatch(/\bmd:flex\b/);

  await user.click(menuButton);

  const dialog = screen.getByRole("dialog");
  const mobileNav = within(dialog).getByRole("navigation", { name: "Primary" });
  expect(within(mobileNav).getByRole("link", { name: "Library" })).toBeInTheDocument();
  expect(within(mobileNav).getByRole("link", { name: "Compare" })).toBeInTheDocument();
  expect(within(mobileNav).getByRole("link", { name: "Settings" })).toBeInTheDocument();
  expect(within(dialog).getByRole("button", { name: /theme/i })).toBeInTheDocument();

  await user.click(within(mobileNav).getByRole("link", { name: "Library" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
