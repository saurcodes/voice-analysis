import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { SettingsPage } from "./SettingsPage";

test("shows account info from the mock auth state", () => {
  renderWithProviders(<SettingsPage />, {
    auth: { user: { name: "Demo User", email: "demo@example.com" } },
  });
  // Scoped to <main>: the header's UserMenu also shows the user's name.
  const main = within(screen.getByRole("main"));
  expect(main.getByText("Demo User")).toBeInTheDocument();
  expect(main.getByText("demo@example.com")).toBeInTheDocument();
});

test("Drive connect is disabled with an explanation", () => {
  renderWithProviders(<SettingsPage />);
  const driveButton = screen.getByRole("button", { name: /connect google drive/i });
  expect(driveButton).toBeDisabled();
  expect(screen.getByText("Available in a later release")).toBeInTheDocument();
});

test("sign out button calls signout", async () => {
  const signout = vi.fn();
  renderWithProviders(<SettingsPage />, { auth: { signout } });

  const main = within(screen.getByRole("main"));
  await userEvent.click(main.getByRole("button", { name: "Sign out" }));
  expect(signout).toHaveBeenCalled();
});
