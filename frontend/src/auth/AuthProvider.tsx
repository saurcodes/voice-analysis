import { useCallback, useMemo, type ReactNode } from "react";
import { AuthProvider as OidcAuthProvider, useAuth } from "react-oidc-context";
import { oidcConfig } from "./oidc";
import { AuthContext, TOKEN_SKEW_S, type AuthState, type AuthUser } from "./context";

function deriveUser(profile: { name?: string; preferred_username?: string; email?: string } | undefined): AuthUser | null {
  if (!profile) return null;
  return {
    name: profile.name ?? profile.preferred_username ?? profile.email ?? "Account",
    email: profile.email ?? "",
  };
}

/** Bridges react-oidc-context's useAuth() into this app's AuthState shape. */
function AuthBridge({ children }: { children: ReactNode }) {
  const auth = useAuth();

  const getToken = useCallback(async (): Promise<string> => {
    const expiresIn = auth.user?.expires_in;
    const expiringSoon = expiresIn === undefined || expiresIn < TOKEN_SKEW_S;
    if (!auth.user?.access_token || expiringSoon) {
      const renewed = await auth.signinSilent();
      if (renewed?.access_token) return renewed.access_token;
    }
    if (!auth.user?.access_token) throw new Error("Not authenticated");
    return auth.user.access_token;
  }, [auth]);

  const signin = useCallback(
    async (returnTo?: string): Promise<void> => {
      await auth.signinRedirect({ state: { returnTo: returnTo ?? "/" } });
    },
    [auth],
  );

  const signout = useCallback(async (): Promise<void> => {
    await auth.signoutRedirect();
  }, [auth]);

  const user = useMemo(() => deriveUser(auth.user?.profile), [auth.user]);

  const value = useMemo<AuthState>(
    () => ({
      isAuthenticated: auth.isAuthenticated,
      isLoading: auth.isLoading,
      user,
      getToken,
      signin,
      signout,
    }),
    [auth.isAuthenticated, auth.isLoading, user, getToken, signin, signout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Wraps react-oidc-context's own AuthProvider (Keycloak OIDC config from src/auth/oidc.ts)
 * and exposes the app-level AuthState shape via useAuthState(). Every consumer written
 * against useAuthState() (RequireAuth, UserMenu, LoginPage, SettingsPage) is unaffected by
 * what's underneath.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <OidcAuthProvider {...oidcConfig}>
      <AuthBridge>{children}</AuthBridge>
    </OidcAuthProvider>
  );
}
