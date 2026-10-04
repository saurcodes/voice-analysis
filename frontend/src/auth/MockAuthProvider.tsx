import { useMemo, type ReactNode } from "react";
import { AuthContext, type AuthState, type AuthUser } from "./context";

/**
 * Stub auth provider for Task 1 scaffolding. Task 2 replaces this with a real
 * react-oidc-context based provider that talks to Keycloak, keeping the same
 * AuthState shape so every consumer written against useAuthState() is unaffected.
 */
export function MockAuthProvider({
  children,
  authenticated = false,
  user = null,
}: {
  children: ReactNode;
  authenticated?: boolean;
  user?: AuthUser | null;
}) {
  const value = useMemo<AuthState>(
    () => ({
      isAuthenticated: authenticated,
      isLoading: false,
      user: authenticated ? user : null,
      getToken: async () => "test-token",
      signin: async () => {},
      signout: async () => {},
    }),
    [authenticated, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
