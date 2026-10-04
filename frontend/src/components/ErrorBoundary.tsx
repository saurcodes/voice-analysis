import { Component, type ErrorInfo, type ReactNode } from "react";
import { WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Last-resort catch for a render or commit error below the routes. Without it React unmounts
 * the whole tree and leaves a blank page (and, if a Radix overlay was open, a body that still
 * has pointer-events: none). The fallback is self-contained (no router, auth or query hooks)
 * so it cannot itself fail for the same reason, and uses the app shell's surface tokens.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[react ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error === null) return this.props.children;
    return (
      <div className="min-h-screen bg-background">
        <header className="h-14 border-b border-border bg-card">
          <div className="mx-auto flex h-full max-w-7xl items-center px-4">
            <span className="font-semibold tracking-tight">Vocal Coach</span>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-8">
          <div
            role="alert"
            className="flex max-w-lg flex-col items-start gap-3 rounded-lg border border-border bg-card p-6"
          >
            <h1 className="flex items-center gap-2 text-base font-semibold text-serious">
              <WarningCircle weight="regular" className="size-5 shrink-0" aria-hidden="true" />
              Something went wrong
            </h1>
            <p className="text-sm text-muted-foreground">
              This page hit an unexpected error. Reloading usually fixes it.
            </p>
            <Button type="button" onClick={() => window.location.reload()}>
              Reload
            </Button>
          </div>
        </main>
      </div>
    );
  }
}
