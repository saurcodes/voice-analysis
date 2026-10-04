import { WebStorageStateStore } from "oidc-client-ts";
import type { AuthProviderProps } from "react-oidc-context";

const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8080";
const KEYCLOAK_REALM = import.meta.env.VITE_KEYCLOAK_REALM ?? "vocal-coach";
const KEYCLOAK_CLIENT_ID = import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "vocal-coach-web";

interface SigninState {
  returnTo?: string;
}

/**
 * Strips the OIDC `code`/`state` query params left by the authorization redirect and
 * sends the user back to wherever RequireAuth sent them before signin (or "/" by
 * default). Keycloak access tokens last 300s; see src/auth/context.tsx for renewal.
 */
function onSigninCallback(user: { state?: unknown } | undefined): void {
  const state = user?.state as SigninState | undefined;
  const returnTo = state?.returnTo ?? "/";
  window.history.replaceState({}, document.title, returnTo);
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
