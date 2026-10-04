import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router";
import { ThemeProvider } from "@/lib/theme";
// Task 1 placeholder; Task 2 swaps this for a real Keycloak-backed provider
// behind the same AuthContext shape (see src/auth/context.tsx).
import { MockAuthProvider } from "@/auth/MockAuthProvider";
import { AppShell } from "@/components/AppShell";

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MockAuthProvider>
          <BrowserRouter>
            <AppShell>
              <p className="text-sm text-muted-foreground">
                Pages land in later tasks of Plan 5.
              </p>
            </AppShell>
          </BrowserRouter>
        </MockAuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
