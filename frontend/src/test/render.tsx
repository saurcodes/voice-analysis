import { render, type RenderResult } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import type { ReactElement, ReactNode } from "react";
import { ThemeProvider } from "@/lib/theme";
import { AuthContext, type AuthState, type AuthUser } from "@/auth/context";

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

function AllProviders({
  children,
  route = "/",
  auth,
}: {
  children: ReactNode;
  route?: string;
  auth?: Partial<AuthState>;
}) {
  const queryClient = createTestQueryClient();
  const authState = buildAuthState(auth);

  return (
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AuthContext.Provider value={authState}>{children}</AuthContext.Provider>
        </ThemeProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}

export function renderWithProviders(
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderResult {
  const { route, auth } = options;
  return render(ui, {
    wrapper: ({ children }) => (
      <AllProviders route={route} auth={auth}>
        {children}
      </AllProviders>
    ),
  });
}
