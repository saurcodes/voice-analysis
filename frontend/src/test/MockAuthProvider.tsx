import type { QueryClient } from "@tanstack/react-query";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { AuthContext, type AuthState } from "@/auth/context";
import { ThemeProvider } from "@/lib/theme";

/**
 * Test-only provider stack: router + query client + theme + a fixed AuthState (no real
 * Keycloak involved). Split out of render.tsx so that file only exports the
 * renderWithProviders() helper (mixing a component export with a helper-function export in
 * one file breaks Fast Refresh; see src/lib/use-theme.ts for the same split elsewhere).
 */
export function MockAuthProvider({
  children,
  route = "/",
  auth,
  queryClient,
}: {
  children: ReactNode;
  route?: string;
  auth: AuthState;
  queryClient: QueryClient;
}) {
  return (
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>
        </ThemeProvider>
      </QueryClientProvider>
    </MemoryRouter>
  );
}
