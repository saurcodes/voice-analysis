import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/msw";
import { driveConfiguredHandlers, driveConnectedHandlers } from "@/test/handlers";
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

test("Drive section shows the not-configured text and no button when the server has no Google credentials", async () => {
  renderWithProviders(<SettingsPage />);
  expect(await screen.findByText("Google Drive is not configured on this server")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /connect google drive/i })).not.toBeInTheDocument();
});

test("Connect Google Drive fetches the consent URL and navigates the page there", async () => {
  server.use(...driveConfiguredHandlers());
  const assign = vi.fn();
  const originalLocation = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, assign },
  });

  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />);

  const connectButton = await screen.findByRole("button", { name: /connect google drive/i });
  await user.click(connectButton);

  await waitFor(() =>
    expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?mock=1"),
  );

  Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
});

test("when connected, shows the linked email and disconnects after confirming", async () => {
  server.use(...driveConnectedHandlers("coach@gmail.com"));

  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />);

  expect(await screen.findByText("Connected as coach@gmail.com")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("Disconnect Google Drive?")).toBeInTheDocument();
  expect(within(dialog).getByText("Analyses you already made stay.")).toBeInTheDocument();

  let disconnectCalled = false;
  server.use(
    http.delete("/api/drive/connect", () => {
      disconnectCalled = true;
      return new HttpResponse(null, { status: 204 });
    }),
    http.get("/api/me", () =>
      HttpResponse.json({
        id: "00000000-0000-0000-0000-000000000001",
        email: "demo@example.com",
        username: "Demo User",
        drive_configured: true,
        drive_connected: false,
        google_email: null,
        llm_enabled: false,
        llm_provider: null,
      }),
    ),
  );

  await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));

  await waitFor(() => expect(disconnectCalled).toBe(true));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /connect google drive/i })).toBeInTheDocument(),
  );
});

test("a drive=connected redirect shows a success note", () => {
  renderWithProviders(<SettingsPage />, { route: "/settings?drive=connected" });
  expect(screen.getByText("Google Drive connected")).toBeInTheDocument();
});

test("a drive=cancelled redirect shows a cancelled note", () => {
  renderWithProviders(<SettingsPage />, { route: "/settings?drive=cancelled" });
  expect(screen.getByText("Connection cancelled")).toBeInTheDocument();
});

test("sign out button calls signout", async () => {
  const signout = vi.fn();
  renderWithProviders(<SettingsPage />, { auth: { signout } });

  const main = within(screen.getByRole("main"));
  await userEvent.click(main.getByRole("button", { name: "Sign out" }));
  expect(signout).toHaveBeenCalled();
});
