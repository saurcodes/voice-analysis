import { lazy, Suspense, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { ThemeProvider } from "@/lib/theme";
import { AuthProvider } from "@/auth/AuthProvider";
import { RequireAuth } from "@/auth/RequireAuth";
import { AppShell } from "@/components/AppShell";
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

function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <AuthProvider>
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
          </AuthProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </BrowserRouter>
  );
}

export default App;
