import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { server } from "@/test/msw";
import { MockAuthProvider } from "@/test/MockAuthProvider";
import type { AuthState } from "@/auth/context";
import { jobStatus, summary } from "@/test/fixtures";
import { useJobs, useSummaries } from "./hooks";

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
