import { createContext } from "react";
import type { AppConfig } from "@/config";

/**
 * Carries the runtime AppConfig (loaded once in src/bootstrap.tsx, before App ever mounts)
 * down to AuthProvider, which cannot take it as a prop without App.tsx itself changing
 * (App.tsx constructs `<AuthProvider>` with no props and is not part of this plan task).
 * AuthProvider reads this via useContext and builds the oidc-client-ts config from it with
 * buildOidcConfig() (src/auth/oidc.ts). Tests pass an `oidcConfig` prop to AuthProvider
 * directly instead of wrapping it in this context.
 */
export const ConfigContext = createContext<AppConfig | null>(null);
