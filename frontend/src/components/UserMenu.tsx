import { Button } from "@/components/ui/button";
import { useAuthState } from "@/auth/context";

/**
 * Minimal user menu slot for Task 1. Task 2 replaces this with a real dropdown
 * (account info, Drive connect state, sign out) once Keycloak is wired in.
 */
export function UserMenu() {
  const { isAuthenticated, user, signin, signout } = useAuthState();

  if (!isAuthenticated || !user) {
    return (
      <Button variant="outline" size="sm" onClick={() => void signin()}>
        Sign in
      </Button>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-muted-foreground">{user.name}</span>
      <Button variant="ghost" size="sm" onClick={() => void signout()}>
        Sign out
      </Button>
    </div>
  );
}
