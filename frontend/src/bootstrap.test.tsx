import { act } from "react";
import { within } from "@testing-library/react";
import type { ReactNode } from "react";
import { ConfigError } from "./config";
import { renderApp } from "./bootstrap";

// App.tsx mounts the real AuthProvider (src/auth/AuthProvider.tsx), which wraps
// react-oidc-context's AuthProvider; mocked here the same way src/auth/AuthProvider.test.tsx
// does, so rendering the full App tree in the "success" case below never touches the network.
const { mockUseAuth, mockHasAuthParams } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockHasAuthParams: vi.fn(() => false),
}));

vi.mock("react-oidc-context", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: mockUseAuth,
  hasAuthParams: mockHasAuthParams,
}));

beforeEach(() => {
  mockHasAuthParams.mockReturnValue(false);
  // Not authenticated and still loading: RequireAuth renders its full-page busy skeleton
  // without calling signin(), so mounting App stays entirely offline.
  mockUseAuth.mockReturnValue({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    signinSilent: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });
});

function createContainer(): HTMLElement {
  const container = document.createElement("div");
  document.body.appendChild(container);
  return container;
}

test("renders a Configuration error panel with the failure message when the loader rejects", async () => {
  const container = createContainer();
  const loadConfigImpl = vi.fn().mockRejectedValue(new ConfigError("/config.json responded with 404"));

  const root = await act(() => renderApp(container, loadConfigImpl));

  expect(within(container).getByText("Configuration error")).toBeInTheDocument();
  expect(within(container).getByText("/config.json responded with 404")).toBeInTheDocument();
  expect(within(container).getByText("Check /config.json")).toBeInTheDocument();

  act(() => root.unmount());
  container.remove();
});

test("renders the app once the config loader resolves", async () => {
  const container = createContainer();
  const loadConfigImpl = vi.fn().mockResolvedValue({
    keycloakUrl: "http://localhost:8080",
    keycloakRealm: "vocal-coach",
    keycloakClientId: "vocal-coach-web",
  });

  const root = await act(() => renderApp(container, loadConfigImpl));

  expect(within(container).queryByText("Configuration error")).not.toBeInTheDocument();
  // RequireAuth's full-page skeleton (isLoading: true, isAuthenticated: false from the mock
  // above) is the first thing the real App renders without a signed-in session.
  expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument();

  act(() => root.unmount());
  container.remove();
});
