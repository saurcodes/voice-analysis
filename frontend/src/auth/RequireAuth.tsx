import { useEffect, useRef, type ReactNode } from "react";
import { useLocation } from "react-router";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthState } from "./context";

/**
 * Route guard: renders children once authenticated, sends unauthenticated visitors to
 * Keycloak (carrying the current path+search as returnTo), and shows a full-page skeleton
 * while the OIDC client is still figuring out whether there's a session.
 *
 * isLoading is also true for the whole duration of a background navigator call on an
 * already-authenticated session (e.g. getToken()'s own silent renew, or
 * automaticSilentRenew) - react-oidc-context ties isLoading to activeNavigator for every
 * navigator method, not just the initial bootstrap. So both the skeleton and the signin
 * redirect are gated on `!isAuthenticated` too: otherwise every mid-session renew would
 * unmount the authenticated page and flash the skeleton (or, worse, fire a redundant
 * signin() while activeNavigator is already set).
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, activeNavigator, signin } = useAuthState();
  const location = useLocation();
  const requestedSignin = useRef(false);
  const currentPath = `${location.pathname}${location.search}`;

  useEffect(() => {
    if (isLoading || isAuthenticated || activeNavigator || requestedSignin.current) return;
    requestedSignin.current = true;
    void signin(currentPath);
  }, [isLoading, isAuthenticated, activeNavigator, signin, currentPath]);

  if (isLoading && !isAuthenticated) {
    return (
      <div className="flex min-h-screen flex-col gap-4 p-8" aria-busy="true">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-full max-w-md" />
        <Skeleton className="h-4 w-full max-w-sm" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (!isAuthenticated) return null;

  return <>{children}</>;
}
