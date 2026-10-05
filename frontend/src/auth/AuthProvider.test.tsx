import { render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AuthProvider } from "./AuthProvider";
import { buildOidcConfig } from "./oidc";
import { ConfigContext } from "./ConfigContext";
import { useAuthState } from "./context";

const { mockUseAuth, mockHasAuthParams } = vi.hoisted(() => ({
  mockUseAuth: vi.fn(),
  mockHasAuthParams: vi.fn(() => false),
}));

vi.mock("react-oidc-context", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: mockUseAuth,
  hasAuthParams: mockHasAuthParams,
}));

// react-oidc-context's own AuthProvider is mocked above to just render its children, so the
// actual values here are never read by anything in these tests; they only need to be a valid
// oidcConfig prop so AuthProvider doesn't throw its "missing config" error.
const testOidcConfig = buildOidcConfig({
  keycloakUrl: "http://localhost:8080",
  keycloakRealm: "vocal-coach",
  keycloakClientId: "vocal-coach-web",
});

function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider oidcConfig={testOidcConfig}>{children}</AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  mockHasAuthParams.mockReturnValue(false);
});

test("getToken renews when the token is expiring soon and returns the renewed token", async () => {
  const signinSilent = vi.fn().mockResolvedValue({ access_token: "new" });
  mockUseAuth.mockReturnValue({
    user: { access_token: "old", expires_in: 5, profile: {} },
    isAuthenticated: true,
    isLoading: false,
    signinSilent,
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  const { result } = renderHook(() => useAuthState(), { wrapper });
  await expect(result.current.getToken()).resolves.toBe("new");
  expect(signinSilent).toHaveBeenCalledTimes(1);
});

test("two concurrent getToken calls with an expiring token share one signinSilent", async () => {
  let resolveRenew: ((user: { access_token: string }) => void) | undefined;
  const signinSilent = vi.fn(
    () =>
      new Promise<{ access_token: string }>((resolve) => {
        resolveRenew = resolve;
      }),
  );
  mockUseAuth.mockReturnValue({
    user: { access_token: "old", expires_in: 5, profile: {} },
    isAuthenticated: true,
    isLoading: false,
    signinSilent,
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  const { result } = renderHook(() => useAuthState(), { wrapper });
  const first = result.current.getToken();
  const second = result.current.getToken();
  resolveRenew?.({ access_token: "new" });

  await expect(first).resolves.toBe("new");
  await expect(second).resolves.toBe("new");
  expect(signinSilent).toHaveBeenCalledTimes(1);
});

test("getToken keeps the same identity across auth state changes", () => {
  const authValue = {
    user: { access_token: "tok", expires_in: 300, profile: {} },
    isAuthenticated: true,
    isLoading: false,
    signinSilent: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  };
  mockUseAuth.mockReturnValue(authValue);
  const { result, rerender } = renderHook(() => useAuthState(), { wrapper });
  const firstGetToken = result.current.getToken;

  mockUseAuth.mockReturnValue({ ...authValue, isLoading: true, activeNavigator: "signinSilent" });
  rerender();

  expect(result.current.getToken).toBe(firstGetToken);
});

test("getToken falls back to the existing token when signinSilent resolves null", async () => {
  // react-oidc-context swallows signinSilent errors internally and resolves null rather
  // than rejecting; getToken() must not hang or throw in that case.
  const signinSilent = vi.fn().mockResolvedValue(null);
  mockUseAuth.mockReturnValue({
    user: { access_token: "old", expires_in: 5, profile: {} },
    isAuthenticated: true,
    isLoading: false,
    signinSilent,
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  const { result } = renderHook(() => useAuthState(), { wrapper });
  await expect(result.current.getToken()).resolves.toBe("old");
  expect(signinSilent).toHaveBeenCalledTimes(1);
});

test("navigates to state.returnTo via React Router after a signin callback", async () => {
  mockHasAuthParams.mockReturnValue(true);
  mockUseAuth.mockReturnValue({
    user: { access_token: "tok", expires_in: 300, profile: {}, state: { returnTo: "/settings" } },
    isAuthenticated: true,
    isLoading: false,
    signinSilent: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  render(
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider oidcConfig={testOidcConfig}>
        <Routes>
          <Route path="/" element={<p>home probe</p>} />
          <Route path="/settings" element={<p>settings probe</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );

  expect(await screen.findByText("settings probe")).toBeInTheDocument();
});

test("renders nothing while a signin callback is still being processed", () => {
  mockHasAuthParams.mockReturnValue(true);
  mockUseAuth.mockReturnValue({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    signinSilent: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  render(
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider oidcConfig={testOidcConfig}>
        <p>home probe</p>
      </AuthProvider>
    </MemoryRouter>,
  );

  expect(screen.queryByText("home probe")).not.toBeInTheDocument();
});

test("does not navigate on an ordinary authenticated page load (no signin callback in progress)", () => {
  // hasAuthParams() is false here (default), simulating a plain page load/refresh of an
  // already-authenticated session whose persisted User still carries an old returnTo from
  // the original signin. Regression guard: this must NOT redirect away from "/".
  mockUseAuth.mockReturnValue({
    user: { access_token: "tok", expires_in: 300, profile: {}, state: { returnTo: "/settings" } },
    isAuthenticated: true,
    isLoading: false,
    signinSilent: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  render(
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider oidcConfig={testOidcConfig}>
        <Routes>
          <Route path="/" element={<p>home probe</p>} />
          <Route path="/settings" element={<p>settings probe</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );

  expect(screen.getByText("home probe")).toBeInTheDocument();
  expect(screen.queryByText("settings probe")).not.toBeInTheDocument();
});

test("builds the oidc config from ConfigContext when no oidcConfig prop is given", () => {
  mockUseAuth.mockReturnValue({
    user: null,
    isAuthenticated: false,
    isLoading: false,
    signinSilent: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  render(
    <MemoryRouter initialEntries={["/"]}>
      <ConfigContext.Provider
        value={{ keycloakUrl: "http://kc.example", keycloakRealm: "r", keycloakClientId: "c" }}
      >
        <AuthProvider>
          <p>child probe</p>
        </AuthProvider>
      </ConfigContext.Provider>
    </MemoryRouter>,
  );

  expect(screen.getByText("child probe")).toBeInTheDocument();
});

test("throws a clear error when neither an oidcConfig prop nor a ConfigContext value is given", () => {
  mockUseAuth.mockReturnValue({
    user: null,
    isAuthenticated: false,
    isLoading: false,
    signinSilent: vi.fn(),
    signinRedirect: vi.fn(),
    signoutRedirect: vi.fn(),
  });

  // AuthProvider throws synchronously during render; with no error boundary in this tree,
  // that throw propagates out of render(), so the assertion wraps the render call itself.
  expect(() =>
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <p>child probe</p>
        </AuthProvider>
      </MemoryRouter>,
    ),
  ).toThrow(/oidcConfig prop or a ConfigContext value/);
});
