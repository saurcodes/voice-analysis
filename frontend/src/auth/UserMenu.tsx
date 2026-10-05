import { SignOut } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { useAuthState } from "./context";

/** Mounted in the AppShell header: shows the signed-in user's name and a sign-out action. */
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
      {/* Hidden below md to free up room in the narrow mobile header; AppShell no longer
          needs a descendant selector to achieve this. */}
      <span className="hidden text-sm text-muted-foreground md:inline">{user.name}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Sign out"
        onClick={() => void signout()}
      >
        <SignOut weight="regular" className="size-5" />
      </Button>
    </div>
  );
}
