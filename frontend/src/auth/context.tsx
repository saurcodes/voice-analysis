import { createContext, useContext } from "react";

export interface AuthUser {
  name: string;
  email: string;
}

export interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: AuthUser | null;
  getToken: () => Promise<string>;
  signin: (returnTo?: string) => Promise<void>;
  signout: () => Promise<void>;
}

// Placeholder for Task 1 / Task 2 wiring. Task 2 replaces the provider's implementation
// with real Keycloak OIDC (oidc-client-ts + react-oidc-context) behind this same shape.
export const AuthContext = createContext<AuthState | null>(null);

export function useAuthState(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuthState must be used within an AuthContext provider");
  return ctx;
}
