import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { ThemeProvider } from "@/lib/theme";
import { AuthProvider } from "@/auth/AuthProvider";
import { RequireAuth } from "@/auth/RequireAuth";
import { AppShell } from "@/components/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Skeleton } from "@/components/ui/skeleton";
import { LibraryPage } from "@/pages/LibraryPage";
import { LoginPage } from "@/pages/LoginPage";
import { SettingsPage } from "@/pages/SettingsPage";

// The chart-heavy pages (Recharts) load on demand, keeping the Library entry chunk small.
const AnalysisPage = lazy(() =>
  import("@/pages/AnalysisPage").then((module) => ({ default: module.AnalysisPage })),
);
const ComparePage = lazy(() =>
  import("@/pages/ComparePage").then((module) => ({ default: module.ComparePage })),
);

const queryClient = new QueryClient();

/** Shown while a lazy page's chunk loads: the shell plus a header and content skeleton, the
 * same shape both lazy pages show while their own data loads. */
function PageSkeleton() {
  return (
    <AppShell>
      <div className="flex flex-col gap-6" aria-busy="true">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-4 w-40" />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function LazyPage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageSkeleton />}>{children}</Suspense>;
}

const POINTER_LOCK_CHECK_MS = 2000;

/** Dev-only watchdog: Radix sets body pointer-events: none while a modal layer is open and
 * clears it on close. If a component crashes mid-close the style can stick, leaving a page
 * that ignores every click with no visible cause; this makes that state loud in the console. */
function usePointerLockWatchdog() {
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const timer = window.setInterval(() => {
      if (document.body.style.pointerEvents !== "none") return;
      const openLayer = document.querySelector(
        '[role="dialog"][data-state="open"], [data-radix-popper-content-wrapper]',
      );
      if (openLayer === null) {
        console.warn("[pointer-lock] body has pointer-events: none but no dialog or popper is open");
      }
    }, POINTER_LOCK_CHECK_MS);
    return () => window.clearInterval(timer);
  }, []);
}

function App() {
  usePointerLockWatchdog();
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AuthProvider>
            <ErrorBoundary>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route
                  path="/settings"
                  element={
                    <RequireAuth>
                      <SettingsPage />
                    </RequireAuth>
                  }
                />
                <Route
                  path="/"
                  element={
                    <RequireAuth>
                      <LibraryPage />
                    </RequireAuth>
                  }
                />
                <Route
                  path="/analyses/:id"
                  element={
                    <RequireAuth>
                      <LazyPage>
                        <AnalysisPage />
                      </LazyPage>
                    </RequireAuth>
                  }
                />
                <Route
                  path="/compare"
                  element={
                    <RequireAuth>
                      <LazyPage>
                        <ComparePage />
                      </LazyPage>
                    </RequireAuth>
                  }
                />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </ErrorBoundary>
          </AuthProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
