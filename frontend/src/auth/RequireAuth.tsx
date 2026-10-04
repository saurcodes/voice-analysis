import { useEffect, useRef, type ReactNode } from "react";
import { useLocation } from "react-router";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuthState } from "./context";

/**
 * Route guard: renders children once authenticated, sends unauthenticated visitors to
 * Keycloak (carrying the current path+search as returnTo), and shows a full-page skeleton
 * while the OIDC client is still figuring out whether there's a session.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, signin } = useAuthState();
  const location = useLocation();
  const requestedSignin = useRef(false);
  const currentPath = `${location.pathname}${location.search}`;

  useEffect(() => {
    if (isLoading || isAuthenticated || requestedSignin.current) return;
    requestedSignin.current = true;
    void signin(currentPath);
  }, [isLoading, isAuthenticated, signin, currentPath]);

  if (isLoading) {
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
