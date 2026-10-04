import { createContext } from "react";
import type { Theme } from "./theme";

export interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

// Split out of theme.tsx (which exports the ThemeProvider component) and use-theme.ts
// (which exports the useTheme hook) so neither file mixes a component export with a
// non-component export; see src/auth/context.tsx for the same pattern applied to auth.
export const ThemeContext = createContext<ThemeContextValue | null>(null);
