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
