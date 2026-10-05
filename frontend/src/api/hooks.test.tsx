import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { server } from "@/test/msw";
import { MockAuthProvider } from "@/test/MockAuthProvider";
import type { AuthState } from "@/auth/context";
import { jobStatus, summary } from "@/test/fixtures";
import { useApi, useDisconnectDrive, useDriveConnect, useDriveFiles, useJobs, useSummaries } from "./hooks";

function buildAuth(overrides: Partial<AuthState> = {}): AuthState {
  return {
    isAuthenticated: true,
    isLoading: false,
    user: { name: "Demo User", email: "demo@example.com" },
    getToken: async () => "test-token",
    signin: async () => {},
    signout: async () => {},
    ...overrides,
  };
}

function createWrapper(auth: AuthState = buildAuth()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MockAuthProvider auth={auth} queryClient={queryClient}>
        {children}
      </MockAuthProvider>
    );
  };
}

afterEach(() => {
  vi.useRealTimers();
});

test("useApi's onUnauthorized signs in again with the current path and search as returnTo", async () => {
  server.use(http.get("/api/me", () => HttpResponse.json({ detail: "expired" }, { status: 401 })));
  const signin = vi.fn(async () => {});
  const auth = buildAuth({ signin });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MockAuthProvider auth={auth} queryClient={queryClient} route="/compare?ids=a,b">
        {children}
      </MockAuthProvider>
    );
  }

  const { result } = renderHook(() => useApi(), { wrapper: Wrapper });
  await expect(result.current.get("/api/me")).rejects.toMatchObject({ status: 401 });

  expect(signin).toHaveBeenCalledTimes(1);
  expect(signin).toHaveBeenCalledWith("/compare?ids=a,b");
});

test("useSummaries keeps the previous page's data while the next page loads", async () => {
  server.use(
    http.get("/api/analyses", async ({ request }) => {
      const offset = new URL(request.url).searchParams.get("offset");
      if (offset === "0") return HttpResponse.json([summary({ id: "first-page" })]);
      await new Promise((resolve) => setTimeout(resolve, 50));
      return HttpResponse.json([summary({ id: "second-page" })]);
    }),
  );

  const { result, rerender } = renderHook(({ offset }) => useSummaries({ limit: 1, offset }), {
    wrapper: createWrapper(),
    initialProps: { offset: 0 },
  });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  rerender({ offset: 1 });
  expect(result.current.isPlaceholderData).toBe(true);
  expect(result.current.data?.[0]).toMatchObject({ id: "first-page" });

  await waitFor(() => expect(result.current.data?.[0]).toMatchObject({ id: "second-page" }));
});

test("useSummaries resolves with the fixture summaries list", async () => {
  const { result } = renderHook(() => useSummaries(), { wrapper: createWrapper() });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  expect(result.current.data).toHaveLength(3);
  expect(result.current.data?.[0]).toMatchObject({ file_name: "practice-run.wav" });
});

test("useSummaries passes limit and offset through as query params", async () => {
  let capturedUrl = "";
  server.use(
    http.get("/api/analyses", ({ request }) => {
      capturedUrl = request.url;
      return HttpResponse.json([summary()]);
    }),
  );

  const { result } = renderHook(() => useSummaries({ limit: 5, offset: 10 }), {
    wrapper: createWrapper(),
  });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(capturedUrl).toContain("limit=5");
  expect(capturedUrl).toContain("offset=10");
});

test("useJobs refetches every 5s while a job is queued or running", async () => {
  let calls = 0;
  server.use(
    http.get("/api/jobs", () => {
      calls += 1;
      return HttpResponse.json([jobStatus({ status: "running" })]);
    }),
  );

  vi.useFakeTimers();
  const { result } = renderHook(() => useJobs(), { wrapper: createWrapper() });
  await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(calls).toBe(1);

  await vi.advanceTimersByTimeAsync(5000);
  expect(calls).toBe(2);
});

test("useJobs stops refetching once no job is queued or running", async () => {
  let calls = 0;
  server.use(
    http.get("/api/jobs", () => {
      calls += 1;
      return HttpResponse.json([jobStatus({ status: "done" })]);
    }),
  );

  vi.useFakeTimers();
  const { result } = renderHook(() => useJobs(), { wrapper: createWrapper() });
  await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(calls).toBe(1);

  await vi.advanceTimersByTimeAsync(6000);
  expect(calls).toBe(1);
});

test("useDriveConnect sends credentials so the HttpOnly oauth state cookie round-trips", async () => {
  let capturedCredentials: RequestCredentials | undefined;
  server.use(
    http.get("/api/drive/connect", ({ request }) => {
      capturedCredentials = request.credentials;
      return HttpResponse.json({ url: "https://accounts.google.com/o/oauth2/v2/auth?mock=1" });
    }),
  );
  const originalLocation = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, assign: vi.fn() },
  });

  const { result } = renderHook(() => useDriveConnect(), { wrapper: createWrapper() });
  result.current.mutate();

  await waitFor(() => expect(capturedCredentials).toBe("include"));

  Object.defineProperty(window, "location", { configurable: true, value: originalLocation });
});

test("useDisconnectDrive treats a 404 as success and invalidates both the me and drive queries", async () => {
  server.use(http.delete("/api/drive/connect", () => HttpResponse.json({ detail: "not found" }, { status: 404 })));

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MockAuthProvider auth={buildAuth()} queryClient={queryClient}>
        {children}
      </MockAuthProvider>
    );
  }
  queryClient.setQueryData(["vc", "me"], { drive_connected: true });
  queryClient.setQueryData(["vc", "drive", "files", "root"], []);

  const { result } = renderHook(() => useDisconnectDrive(), { wrapper: Wrapper });
  result.current.mutate();

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(queryClient.getQueryState(["vc", "me"])?.isInvalidated).toBe(true);
  expect(queryClient.getQueryState(["vc", "drive", "files", "root"])?.isInvalidated).toBe(true);
});

test("useDriveFiles invalidates the me query on a 409 (drive no longer connected)", async () => {
  server.use(
    http.get("/api/drive/files", () => HttpResponse.json({ detail: "drive_not_connected" }, { status: 409 })),
  );

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MockAuthProvider auth={buildAuth()} queryClient={queryClient}>
        {children}
      </MockAuthProvider>
    );
  }
  queryClient.setQueryData(["vc", "me"], { drive_connected: true });

  const { result } = renderHook(() => useDriveFiles("root"), { wrapper: Wrapper });

  await waitFor(() => expect(result.current.isError).toBe(true));
  await waitFor(() => expect(queryClient.getQueryState(["vc", "me"])?.isInvalidated).toBe(true));
});
