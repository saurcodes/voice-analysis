import { GoogleDriveLogo } from "@phosphor-icons/react";
import { AppShell, ThemeToggle } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import { useAuthState } from "@/auth/context";

export function SettingsPage() {
  const { user, signout } = useAuthState();

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl">
        <h1 className="text-xl font-semibold tracking-tight">Settings</h1>

        <div className="mt-6 divide-y divide-border border-t border-border">
          <section className="py-6">
            <h2 className="text-sm font-medium">Account</h2>
            <dl className="mt-3 space-y-2">
              <div className="flex items-center justify-between gap-4">
                <dt className="text-sm text-muted-foreground">Name</dt>
                <dd className="text-sm">{user?.name}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-sm text-muted-foreground">Email</dt>
                <dd className="text-sm">{user?.email}</dd>
              </div>
            </dl>
          </section>

          <section className="py-6">
            <h2 className="text-sm font-medium">Google Drive</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Import recordings directly from Drive once this is available.
            </p>
            <div className="mt-3 flex items-center gap-3">
              <Button variant="outline" disabled>
                <GoogleDriveLogo weight="regular" className="size-4" />
                Connect Google Drive
              </Button>
              <span className="text-sm text-muted-foreground">Available in a later release</span>
            </div>
          </section>

          <section className="py-6">
            <h2 className="text-sm font-medium">Theme</h2>
            <p className="mt-1 text-sm text-muted-foreground">Choose how Vocal Coach looks on this device.</p>
            <div className="mt-3">
              <ThemeToggle />
            </div>
          </section>

          <section className="py-6">
            <Button variant="secondary" onClick={() => void signout()}>
              Sign out
            </Button>
          </section>
        </div>
      </div>
    </AppShell>
  );
}
