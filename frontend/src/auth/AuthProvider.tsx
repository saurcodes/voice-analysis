import { useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AuthProvider as OidcAuthProvider, hasAuthParams, useAuth } from "react-oidc-context";
import type { AuthProviderNoUserManagerProps } from "react-oidc-context";
import type { User } from "oidc-client-ts";
import { useNavigate } from "react-router";
import { buildOidcConfig } from "./oidc";
import { ConfigContext } from "./ConfigContext";
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
 *
 * While a signin callback is still being processed it renders nothing, so the callback URL's
 * own route ("/") does not flash for a frame before the navigation to returnTo lands. If the
 * callback fails (not loading, not authenticated) the children render as usual and the
 * normal unauthenticated flow takes over.
 */
function SigninCallbackRedirect({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const navigate = useNavigate();
  const [wasSigninCallback] = useState(() => hasAuthParams());
  const [handled, setHandled] = useState(false);
  const navigated = useRef(false);

  useEffect(() => {
    if (!wasSigninCallback || navigated.current || !auth.isAuthenticated) return;
    navigated.current = true;
    const state = auth.user?.state as SigninState | undefined;
    const returnTo = typeof state?.returnTo === "string" ? state.returnTo : "/";
    // Children stay hidden until the navigation has been issued; the flag flips in a
    // microtask after it, so the first frame they render is already at returnTo.
    void Promise.resolve(navigate(returnTo, { replace: true })).then(() => setHandled(true));
  }, [wasSigninCallback, auth.isAuthenticated, auth.user, navigate]);

  const callbackPending = wasSigninCallback && !handled && (auth.isLoading || auth.isAuthenticated);
  if (callbackPending) return null;
  return <>{children}</>;
}

/**
 * Bridges react-oidc-context's useAuth() into this app's AuthState shape.
 *
 * getToken/signin/signout read the latest useAuth() value through a ref, so their
 * identities never change: every auth state transition (including each background silent
 * renew) would otherwise hand consumers new functions, rebuilding the API client and
 * restarting every job watcher. Concurrent getToken() calls that all find the token
 * expiring share one in-flight signinSilent() instead of each starting their own.
 */
function AuthBridge({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const authRef = useRef(auth);
  const renewRef = useRef<Promise<User | null> | null>(null);

  useLayoutEffect(() => {
    authRef.current = auth;
  });

  const getToken = useCallback(async (): Promise<string> => {
    const current = authRef.current;
    const expiresIn = current.user?.expires_in;
    const expiringSoon = expiresIn === undefined || expiresIn < TOKEN_SKEW_S;
    if (!current.user?.access_token || expiringSoon) {
      if (!renewRef.current) {
        renewRef.current = current.signinSilent().finally(() => {
          renewRef.current = null;
        });
      }
      const renewed = await renewRef.current;
      if (renewed?.access_token) return renewed.access_token;
    }
    const latest = authRef.current.user?.access_token ?? current.user?.access_token;
    if (!latest) throw new Error("Not authenticated");
    return latest;
  }, []);

  const signin = useCallback(async (returnTo?: string): Promise<void> => {
    await authRef.current.signinRedirect({ state: { returnTo: returnTo ?? "/" } });
  }, []);

  const signout = useCallback(async (): Promise<void> => {
    await authRef.current.signoutRedirect();
  }, []);

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
 * Wraps react-oidc-context's own AuthProvider and exposes the app-level AuthState shape via
 * useAuthState(). Every consumer written against useAuthState() (RequireAuth, UserMenu,
 * LoginPage, SettingsPage) is unaffected by what's underneath. Must be mounted under
 * BrowserRouter (App.tsx does this): SigninCallbackRedirect calls useNavigate().
 *
 * The Keycloak settings come from one of two places:
 *   - an explicit `oidcConfig` prop (tests, or any other direct caller);
 *   - otherwise, the runtime AppConfig provided via ConfigContext, built into an
 *     oidc-client-ts config with buildOidcConfig() (src/auth/oidc.ts).
 * App.tsx mounts `<AuthProvider>` with no props and is not part of this plan task, so the
 * config can't be threaded through as a required prop there; src/bootstrap.tsx wraps App in
 * a ConfigContext.Provider after loading /config.json instead.
 */
export function AuthProvider({
  children,
  oidcConfig,
}: {
  children: ReactNode;
  oidcConfig?: AuthProviderNoUserManagerProps;
}) {
  const config = useContext(ConfigContext);
  const resolvedOidcConfig = oidcConfig ?? (config ? buildOidcConfig(config) : null);

  if (!resolvedOidcConfig) {
    throw new Error(
      "AuthProvider requires either an oidcConfig prop or a ConfigContext value (see src/bootstrap.tsx)",
    );
  }

  return (
    <OidcAuthProvider {...resolvedOidcConfig}>
      <AuthBridge>
        <SigninCallbackRedirect>{children}</SigninCallbackRedirect>
      </AuthBridge>
    </OidcAuthProvider>
  );
}
