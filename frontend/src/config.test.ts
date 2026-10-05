import { ConfigError, loadConfig } from "./config";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

test("resolves the config from a valid JSON body", async () => {
  const fetchImpl = vi.fn().mockResolvedValue(
    jsonResponse({
      keycloakUrl: "http://localhost:8080",
      keycloakRealm: "vocal-coach",
      keycloakClientId: "vocal-coach-web",
    }),
  );

  await expect(loadConfig(fetchImpl)).resolves.toEqual({
    keycloakUrl: "http://localhost:8080",
    keycloakRealm: "vocal-coach",
    keycloakClientId: "vocal-coach-web",
  });
  expect(fetchImpl).toHaveBeenCalledExactlyOnceWith("/config.json", { cache: "no-store" });
});

test("throws ConfigError on a non-OK HTTP response", async () => {
  const fetchImpl = vi.fn().mockResolvedValue(new Response("not found", { status: 404 }));
  await expect(loadConfig(fetchImpl)).rejects.toThrow(ConfigError);
});

test("throws ConfigError when the response body is not valid JSON", async () => {
  const fetchImpl = vi.fn().mockResolvedValue(new Response("not json", { status: 200 }));
  await expect(loadConfig(fetchImpl)).rejects.toThrow(ConfigError);
});

test("throws ConfigError when a required key is missing", async () => {
  const fetchImpl = vi.fn().mockResolvedValue(
    jsonResponse({ keycloakUrl: "http://localhost:8080", keycloakRealm: "vocal-coach" }),
  );
  await expect(loadConfig(fetchImpl)).rejects.toThrow(ConfigError);
});

test("throws ConfigError when a required key is an empty string", async () => {
  const fetchImpl = vi.fn().mockResolvedValue(
    jsonResponse({ keycloakUrl: "", keycloakRealm: "vocal-coach", keycloakClientId: "vocal-coach-web" }),
  );
  await expect(loadConfig(fetchImpl)).rejects.toThrow(ConfigError);
});

test("throws ConfigError when the fetch itself rejects", async () => {
  const fetchImpl = vi.fn().mockRejectedValue(new Error("network down"));
  await expect(loadConfig(fetchImpl)).rejects.toThrow(ConfigError);
});
