import { createContext, useContext } from "react";

export interface AuthUser {
  name: string;
  email: string;
}

export interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  /**
   * The oidc-client-ts navigator method currently in flight ("signinSilent",
   * "signinRedirect", ...), if any. isLoading is also true for the whole duration of any of
   * these, including a background silent renew on an already-authenticated session, so
   * consumers that only want to gate on "do we not have a session yet" (RequireAuth's
   * full-page skeleton) should check `isLoading && !isAuthenticated` rather than isLoading
   * alone.
   */
  activeNavigator?: string;
  user: AuthUser | null;
  getToken: () => Promise<string>;
  signin: (returnTo?: string) => Promise<void>;
  signout: () => Promise<void>;
}

/**
 * Seconds of remaining access-token lifetime below which getToken() forces a silent
 * renew before handing back a token. Keycloak access tokens last 300s.
 */
export const TOKEN_SKEW_S = 20;

// Real implementation lives in src/auth/AuthProvider.tsx (kept in a separate file so this
// module only exports the context/hook, not a component; see src/lib/use-theme.ts for the
// same split applied to ThemeProvider/useTheme).
export const AuthContext = createContext<AuthState | null>(null);

export function useAuthState(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuthState must be used within an AuthContext provider");
  return ctx;
}
