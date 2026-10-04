import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AuthProvider as OidcAuthProvider, hasAuthParams, useAuth } from "react-oidc-context";
import { useNavigate } from "react-router";
import { oidcConfig } from "./oidc";
import { AuthContext, TOKEN_SKEW_S, type AuthState, type AuthUser } from "./context";

function deriveUser(profile: { name?: string; preferred_username?: string; email?: string } | undefined): AuthUser | null {
  if (!profile) return null;
  return {
    name: profile.name ?? profile.preferred_username ?? profile.email ?? "Account",
    email: profile.email ?? "",
  };
}

interface SigninState {
  returnTo?: string;
}

/**
 * Finishes what oidc.ts's onSigninCallback started: once react-oidc-context reports an
 * authenticated user whose signin state carries a returnTo, navigates there through React
 * Router (so the route tree actually re-renders, unlike a raw history.replaceState()).
 *
 * Gated on hasAuthParams() captured at first render (before react-oidc-context's own effect
 * strips the code/state query params): without it, this would also fire on every ordinary
 * page load of an already-authenticated session, since the persisted User (restored from
 * sessionStorage) still carries whatever returnTo was set during the original signin and
 * would otherwise yank the user back to that old destination on every refresh.
 */
function SigninCallbackRedirect() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [wasSigninCallback] = useState(() => hasAuthParams());
  const handled = useRef(false);

  useEffect(() => {
    if (!wasSigninCallback || handled.current || !auth.isAuthenticated) return;
    const state = auth.user?.state as SigninState | undefined;
    const returnTo = typeof state?.returnTo === "string" ? state.returnTo : "/";
    handled.current = true;
    navigate(returnTo, { replace: true });
  }, [wasSigninCallback, auth.isAuthenticated, auth.user, navigate]);

  return null;
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
      activeNavigator: auth.activeNavigator,
      user,
      getToken,
      signin,
      signout,
    }),
    [auth.isAuthenticated, auth.isLoading, auth.activeNavigator, user, getToken, signin, signout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Wraps react-oidc-context's own AuthProvider (Keycloak OIDC config from src/auth/oidc.ts)
 * and exposes the app-level AuthState shape via useAuthState(). Every consumer written
 * against useAuthState() (RequireAuth, UserMenu, LoginPage, SettingsPage) is unaffected by
 * what's underneath. Must be mounted under BrowserRouter (App.tsx does this):
 * SigninCallbackRedirect calls useNavigate().
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <OidcAuthProvider {...oidcConfig}>
      <SigninCallbackRedirect />
      <AuthBridge>{children}</AuthBridge>
    </OidcAuthProvider>
  );
}
