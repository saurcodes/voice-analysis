import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { ThemeProvider } from "@/lib/theme";
import { AuthProvider } from "@/auth/AuthProvider";
import { RequireAuth } from "@/auth/RequireAuth";
import { AnalysisPage } from "@/pages/AnalysisPage";
import { LibraryPage } from "@/pages/LibraryPage";
import { LoginPage } from "@/pages/LoginPage";
import { SettingsPage } from "@/pages/SettingsPage";

const queryClient = new QueryClient();

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
                    <AnalysisPage />
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
