import { WebStorageStateStore } from "oidc-client-ts";
import type { AuthProviderNoUserManagerProps } from "react-oidc-context";
import type { AppConfig } from "@/config";

/**
 * Strips the OIDC `code`/`state` query params left by the authorization redirect, leaving
 * the browser on the current pathname (redirect_uri is always `${origin}/`, so that's "/").
 *
 * This does NOT also navigate to the signin's `returnTo` state: a raw
 * `history.replaceState()` call changes the address bar but isn't observed by React Router
 * v7's BrowserRouter (it only reacts to navigation through its own history object), so
 * jumping straight to `returnTo` from here would leave `<Routes>` still rendering "/" while
 * the URL shows the real destination. That hop happens in SigninCallbackRedirect
 * (src/auth/AuthProvider.tsx), which runs inside the Router tree and calls useNavigate().
 */
function onSigninCallback(): void {
  window.history.replaceState({}, document.title, window.location.pathname);
}

/**
 * Builds the react-oidc-context AuthProvider config from the runtime AppConfig loaded from
 * /config.json (src/config.ts), rather than from import.meta.env.VITE_KEYCLOAK_* build-time
 * values: one built frontend image can then be redeployed against any Keycloak instance
 * (see frontend/docker-entrypoint.sh).
 */
export function buildOidcConfig(cfg: AppConfig): AuthProviderNoUserManagerProps {
  return {
    authority: `${cfg.keycloakUrl}/realms/${cfg.keycloakRealm}`,
    client_id: cfg.keycloakClientId,
    redirect_uri: `${window.location.origin}/`,
    post_logout_redirect_uri: `${window.location.origin}/login`,
    response_type: "code",
    scope: "openid profile email",
    automaticSilentRenew: true,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    onSigninCallback,
  };
}
