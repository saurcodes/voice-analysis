import { render, type RenderResult } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";
import type { AuthState, AuthUser } from "@/auth/context";
import { MockAuthProvider } from "./MockAuthProvider";

export interface RenderWithProvidersOptions {
  route?: string;
  auth?: Partial<AuthState>;
}

const defaultUser: AuthUser = { name: "Demo User", email: "demo@example.com" };

function buildAuthState(overrides?: Partial<AuthState>): AuthState {
  return {
    isAuthenticated: true,
    isLoading: false,
    user: defaultUser,
    getToken: async () => "test-token",
    signin: async () => {},
    signout: async () => {},
    ...overrides,
  };
}

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderResult {
  const { route, auth } = options;
  const queryClient = createTestQueryClient();
  const authState = buildAuthState(auth);

  return render(ui, {
    wrapper: ({ children }) => (
      <MockAuthProvider route={route} auth={authState} queryClient={queryClient}>
        {children}
      </MockAuthProvider>
    ),
  });
}
