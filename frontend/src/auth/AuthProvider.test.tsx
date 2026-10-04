import { render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router";
import { AuthProvider } from "./AuthProvider";
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

function wrapper({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter initialEntries={["/"]}>
      <AuthProvider>{children}</AuthProvider>
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
      <AuthProvider>
        <Routes>
          <Route path="/" element={<p>home probe</p>} />
          <Route path="/settings" element={<p>settings probe</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );

  expect(await screen.findByText("settings probe")).toBeInTheDocument();
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
      <AuthProvider>
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
