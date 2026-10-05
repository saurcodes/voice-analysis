import { buildOidcConfig } from "./oidc";

test("builds the authority and client id from the given AppConfig", () => {
  const cfg = buildOidcConfig({
    keycloakUrl: "https://auth.example.com",
    keycloakRealm: "some-realm",
    keycloakClientId: "some-client",
  });

  expect(cfg.authority).toBe("https://auth.example.com/realms/some-realm");
  expect(cfg.client_id).toBe("some-client");
  expect(cfg.redirect_uri).toBe(`${window.location.origin}/`);
  expect(cfg.post_logout_redirect_uri).toBe(`${window.location.origin}/login`);
  expect(cfg.response_type).toBe("code");
  expect(cfg.scope).toBe("openid profile email");
  expect(cfg.automaticSilentRenew).toBe(true);
});
