import { WebStorageStateStore } from "oidc-client-ts";
import type { AuthProviderProps } from "react-oidc-context";

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8080";
const KEYCLOAK_REALM = import.meta.env.VITE_KEYCLOAK_REALM ?? "vocal-coach";
const KEYCLOAK_CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "vocal-coach-web";

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

export const oidcConfig: AuthProviderProps = {
  authority: `${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}`,
  client_id: KEYCLOAK_CLIENT_ID,
  redirect_uri: `${window.location.origin}/`,
  post_logout_redirect_uri: `${window.location.origin}/login`,
  response_type: "code",
  scope: "openid profile email",
  automaticSilentRenew: true,
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  onSigninCallback,
};
