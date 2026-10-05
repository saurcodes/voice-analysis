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

test("a Connect failure (e.g. a 503 after a config change) shows an inline alert under the button", async () => {
  server.use(...driveConfiguredHandlers());
  server.use(
    http.get("/api/drive/connect", () =>
      HttpResponse.json({ detail: "drive is not configured on this server" }, { status: 503 }),
    ),
  );

  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />);

  await user.click(await screen.findByRole("button", { name: /connect google drive/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent("drive is not configured on this server");
});

test("a drive=error redirect shows a could-not-connect message", () => {
  renderWithProviders(<SettingsPage />, { route: "/settings?drive=error" });
  expect(screen.getByText("Could not connect Google Drive. Try again.")).toBeInTheDocument();
});

test("the Connect button shows a skeleton instead of flashing while /me loads", async () => {
  server.use(
    http.get("/api/me", async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
      return HttpResponse.json({
        id: "00000000-0000-0000-0000-000000000001",
        email: "demo@example.com",
        username: "Demo User",
        drive_configured: true,
        drive_connected: false,
        google_email: null,
        llm_enabled: false,
        llm_provider: null,
      });
    }),
  );
  renderWithProviders(<SettingsPage />);

  expect(screen.queryByRole("button", { name: /connect google drive/i })).not.toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /connect google drive/i })).toBeInTheDocument();
});

test("when connected with no stored Google email, shows Connected without the word null", async () => {
  server.use(
    http.get("/api/me", () =>
      HttpResponse.json({
        id: "00000000-0000-0000-0000-000000000001",
        email: "demo@example.com",
        username: "Demo User",
        drive_configured: true,
        drive_connected: true,
        google_email: null,
        llm_enabled: false,
        llm_provider: null,
      }),
    ),
  );
  renderWithProviders(<SettingsPage />);

  expect(await screen.findByText("Connected")).toBeInTheDocument();
  expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
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

test("Cancel is disabled while a disconnect is in flight, and a 404 is treated as success", async () => {
  let connected = true;
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.get("/api/me", () =>
      HttpResponse.json({
        id: "00000000-0000-0000-0000-000000000001",
        email: "demo@example.com",
        username: "Demo User",
        drive_configured: true,
        drive_connected: connected,
        google_email: connected ? "coach@gmail.com" : null,
        llm_enabled: false,
        llm_provider: null,
      }),
    ),
    http.delete("/api/drive/connect", async () => {
      await gate;
      connected = false;
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />);

  await screen.findByText("Connected as coach@gmail.com");
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  const dialog = screen.getByRole("dialog");

  await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));

  expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();

  release?.();

  // A 404 (connection already gone) is treated as success: the dialog closes and the Connect
  // button (not an error) comes back.
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /connect google drive/i })).toBeInTheDocument(),
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("a disconnect error clears when the dialog is reopened", async () => {
  server.use(...driveConnectedHandlers("coach@gmail.com"));
  server.use(
    http.delete("/api/drive/connect", () => HttpResponse.json({ detail: "server error" }, { status: 500 })),
  );

  const user = userEvent.setup();
  renderWithProviders(<SettingsPage />);

  await screen.findByText("Connected as coach@gmail.com");
  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));

  expect(await within(dialog).findByRole("alert")).toHaveTextContent("server error");

  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  await user.click(screen.getByRole("button", { name: "Disconnect" }));
  const reopenedDialog = screen.getByRole("dialog");
  expect(within(reopenedDialog).queryByRole("alert")).not.toBeInTheDocument();
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
