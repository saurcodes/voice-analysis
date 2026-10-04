import { http, HttpResponse } from "msw";
import { server } from "@/test/msw";
import { createApi, ApiError } from "./client";

test("adds bearer and parses json", async () => {
  server.use(http.get("/api/me", ({ request }) => {
    expect(request.headers.get("authorization")).toBe("Bearer t1");
    return HttpResponse.json({ id: "u", username: "demo" });
  }));
  const api = createApi(async () => "t1", () => {});
  await expect(api.get("/api/me")).resolves.toMatchObject({ username: "demo" });
});

test("401 renews once then retries; second 401 calls onUnauthorized", async () => {
  let calls = 0;
  server.use(http.get("/api/me", () => (++calls === 1 ? new HttpResponse(null, { status: 401 }) : HttpResponse.json({ id: "u" }))));
  const tokens = ["old", "new"];
  const api = createApi(async () => tokens.shift() ?? "new", () => {});
  await expect(api.get("/api/me")).resolves.toMatchObject({ id: "u" });
  expect(calls).toBe(2);

  const onUnauthorized = vi.fn();
  server.use(http.get("/api/me", () => new HttpResponse(null, { status: 401 })));
  await expect(createApi(async () => "x", onUnauthorized).get("/api/me")).rejects.toBeInstanceOf(ApiError);
  expect(onUnauthorized).toHaveBeenCalled();
});

test("maps detail and 422 lists to ApiError", async () => {
  server.use(http.get("/api/x", () => HttpResponse.json({ detail: "nope" }, { status: 415 })));
  await expect(createApi(async () => "t", () => {}).get("/api/x")).rejects.toMatchObject({ status: 415, detail: "nope" });
  server.use(http.get("/api/y", () => HttpResponse.json({ detail: [{ loc: ["query", "limit"], msg: "too small" }] }, { status: 422 })));
  await expect(createApi(async () => "t", () => {}).get("/api/y")).rejects.toMatchObject({ status: 422, detail: "limit: too small" });
});
