import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { CheckCircle, GoogleDriveLogo, WarningCircle } from "@phosphor-icons/react";
import { useAuthState } from "@/auth/context";
import { ApiError } from "@/api/client";
import { useDisconnectDrive, useDriveConnect, useMe } from "@/api/hooks";
import { AppShell, ThemeToggle } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === "string" ? error.detail : error.message;
  }
  return "Something went wrong. Try again.";
}

function DriveCallbackNote({ status }: { status: "connected" | "cancelled" }) {
  if (status === "connected") {
    return (
      <p className="flex items-center gap-1.5 text-sm text-good">
        <CheckCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
        Google Drive connected
      </p>
    );
  }
  return <p className="text-sm text-muted-foreground">Connection cancelled</p>;
}

function DriveSection() {
  const meQuery = useMe();
  const driveConnect = useDriveConnect();
  const disconnectDrive = useDisconnectDrive();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();

  // Captured once on mount (lazy initializer, never updated again): the callback note stays
  // visible even after the param is stripped from the URL below, and reading it this way
  // (not from an effect-driven state sync) never fires a network call on its own.
  const [callbackStatus] = useState(() => searchParams.get("drive"));

  useEffect(() => {
    if (!searchParams.has("drive")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("drive");
    setSearchParams(next, { replace: true });
    // Runs once: strips the one-time callback param without re-triggering on later changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleConnect() {
    driveConnect.mutate();
  }

  function handleDisconnect() {
    setDisconnectError(null);
    disconnectDrive.mutate(undefined, {
      onSuccess: () => setConfirmOpen(false),
      onError: (error) => setDisconnectError(errorDetail(error)),
    });
  }

  const me = meQuery.data;

  return (
    <section className="py-6">
      <h2 className="text-sm font-medium">Google Drive</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Browse and analyse recordings straight from your Google Drive.
      </p>

      {(callbackStatus === "connected" || callbackStatus === "cancelled") && (
        <div className="mt-3">
          <DriveCallbackNote status={callbackStatus} />
        </div>
      )}

      <div className="mt-3">
        {me?.drive_configured === false ? (
          <p className="text-sm text-muted-foreground">Google Drive is not configured on this server</p>
        ) : me?.drive_connected ? (
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-sm text-good">
              <CheckCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
              Connected as {me.google_email}
            </span>
            <Button type="button" variant="secondary" size="sm" onClick={() => setConfirmOpen(true)}>
              Disconnect
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <Button type="button" variant="outline" onClick={handleConnect} disabled={driveConnect.isPending}>
              <GoogleDriveLogo weight="regular" className="size-4" />
              Connect Google Drive
            </Button>
          </div>
        )}
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disconnect Google Drive?</DialogTitle>
            <DialogDescription>Analyses you already made stay.</DialogDescription>
          </DialogHeader>
          {disconnectError && (
            <p role="alert" className="flex items-center gap-1.5 text-sm text-serious">
              <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
              {disconnectError}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDisconnect}
              disabled={disconnectDrive.isPending}
            >
              Disconnect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

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

          <DriveSection />

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
