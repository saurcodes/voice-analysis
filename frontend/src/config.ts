/** Runtime Keycloak settings read from /config.json (see loadConfig below), replacing the
 * build-time VITE_KEYCLOAK_* variables so one built image can be redeployed against a
 * different Keycloak instance without a rebuild (Plan 8 Task 4). */
export interface AppConfig {
  keycloakUrl: string;
  keycloakRealm: string;
  keycloakClientId: string;
}

const REQUIRED_KEYS = ["keycloakUrl", "keycloakRealm", "keycloakClientId"] as const;

/** Thrown by loadConfig() for any failure to obtain a valid runtime config: a network error, a
 * non-OK HTTP response, a body that is not valid JSON, or JSON missing one of the required,
 * non-empty string keys. src/bootstrap.tsx catches this and renders a "Configuration error"
 * panel instead of the app. */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Fetches the runtime configuration written by the nginx container's entrypoint
 * (docker-entrypoint.sh) in production, or served statically from frontend/public/config.json
 * by the Vite dev server. Always bypasses the HTTP cache: the same path can serve a different
 * body after the container is recreated against a new Keycloak. */
export async function loadConfig(fetchImpl: typeof fetch = fetch): Promise<AppConfig> {
  let response: Response;
  try {
    response = await fetchImpl("/config.json", { cache: "no-store" });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new ConfigError(`Could not fetch /config.json: ${message}`);
  }

  if (!response.ok) {
    throw new ConfigError(`/config.json responded with ${response.status}`);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ConfigError("/config.json is not valid JSON");
  }

  if (typeof data !== "object" || data === null) {
    throw new ConfigError("/config.json did not contain a JSON object");
  }

  const record = data as Record<string, unknown>;
  const missing = REQUIRED_KEYS.filter((key) => !isNonEmptyString(record[key]));
  if (missing.length > 0) {
    throw new ConfigError(`/config.json is missing required key(s): ${missing.join(", ")}`);
  }

  return {
    keycloakUrl: record.keycloakUrl as string,
    keycloakRealm: record.keycloakRealm as string,
    keycloakClientId: record.keycloakClientId as string,
  };
}
