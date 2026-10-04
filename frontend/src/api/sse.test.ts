import { http, HttpResponse } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import { server } from "@/test/msw";
import { jobStatus } from "@/test/fixtures";
import { ApiError } from "./client";
import { POLL_MS, streamJobEvents, watchJob, type JobEvent } from "./sse";

function sseResponse(body: string): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

function throwingSseResponse(firstFrame: string): Response {
  const encoder = new TextEncoder();
  let pulls = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1;
      if (pulls === 1) {
        controller.enqueue(encoder.encode(firstFrame));
        return;
      }
      throw new Error("connection reset");
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

afterEach(() => {
  vi.useRealTimers();
});

test("streamJobEvents calls onEvent in order and resolves with the terminal event", async () => {
  const body =
    'event: stage\ndata: {"stage":"extract","progress_pct":20}\n\n' +
    'event: done\ndata: {"analysis_id":"a1"}\n\n';
  const events: JobEvent[] = [];

  const result = await streamJobEvents("job-1", {
    authFetch: async () => sseResponse(body),
    onEvent: (event) => events.push(event),
  });

  expect(result).toBe("done");
  expect(events).toEqual([
    { event: "stage", data: { stage: "extract", progress_pct: 20 } },
    { event: "done", data: { analysis_id: "a1" } },
  ]);
});

test("streamJobEvents parses CRLF frames from sse-starlette, even when a chunk boundary falls between a terminator's \\r and \\n", async () => {
  // Real shape: sse-starlette 3.x's default separator is "\r\n", not the bare "\n" the SSE
  // spec's own examples use.
  const body =
    'event: stage\r\ndata: {"stage":"extract","progress_pct":20}\r\n\r\n' +
    'event: done\r\ndata: {"analysis_id":"a1"}\r\n\r\n';

  // Split the body into two chunks right inside the "\r\n\r\n" gap between the two frames,
  // between its first "\r" and its "\n", so the first chunk ends with a dangling "\r" that
  // only becomes a real line terminator once the second chunk's leading "\n" arrives.
  const gapIndex = body.indexOf('\r\n\r\nevent: done');
  const splitPoint = gapIndex + 1;
  const chunk1 = body.slice(0, splitPoint);
  const chunk2 = body.slice(splitPoint);
  expect(chunk1.endsWith("\r")).toBe(true);
  expect(chunk2.startsWith("\n")).toBe(true);

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(chunk1));
      controller.enqueue(encoder.encode(chunk2));
      controller.close();
    },
  });
  const response = new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });

  const events: JobEvent[] = [];
  const result = await streamJobEvents("job-1", {
    authFetch: async () => response,
    onEvent: (event) => events.push(event),
  });

  expect(result).toBe("done");
  expect(events).toEqual([
    { event: "stage", data: { stage: "extract", progress_pct: 20 } },
    { event: "done", data: { analysis_id: "a1" } },
  ]);
});

test("streamJobEvents ignores a frame with no event: line", async () => {
  const body = 'data: {"ignored":true}\n\nevent: done\ndata: {"analysis_id":"a1"}\n\n';
  const events: JobEvent[] = [];

  const result = await streamJobEvents("job-1", {
    authFetch: async () => sseResponse(body),
    onEvent: (event) => events.push(event),
  });

  expect(result).toBe("done");
  expect(events).toEqual([{ event: "done", data: { analysis_id: "a1" } }]);
});

test("watchJob falls back to polling after an SSE timeout event, and reports the polled outcome", async () => {
  vi.useFakeTimers();
  let pollCalls = 0;
  server.use(
    http.get("/api/jobs/:id", () => {
      pollCalls += 1;
      return HttpResponse.json(
        pollCalls === 1
          ? jobStatus({ status: "running", stage: "transcribe", progress_pct: 80 })
          : jobStatus({ status: "done", stage: "done", progress_pct: 100, analysis_id: "a1" }),
      );
    }),
  );

  const statuses: Array<{ status: string }> = [];
  const { abort } = watchJob(
    "job-1",
    {
      authFetch: async () => sseResponse('event: timeout\ndata: {}\n\n'),
      getJob: async (id) => {
        const response = await fetch(`/api/jobs/${id}`);
        return response.json();
      },
    },
    (status) => statuses.push(status),
  );

  // Let the SSE stream resolve ("timeout") before the first poll is scheduled.
  await vi.waitFor(() => expect(statuses.length).toBeGreaterThan(0));

  await vi.advanceTimersByTimeAsync(POLL_MS);
  await vi.waitFor(() => expect(pollCalls).toBe(1));

  await vi.advanceTimersByTimeAsync(POLL_MS);
  await vi.waitFor(() => expect(pollCalls).toBe(2));

  expect(statuses.at(-1)).toMatchObject({ status: "done" });
  abort();
});

test("watchJob falls back to polling when the SSE reader throws mid-stream, and reports done", async () => {
  vi.useFakeTimers();
  let pollCalls = 0;
  server.use(
    http.get("/api/jobs/:id", () => {
      pollCalls += 1;
      return HttpResponse.json(
        pollCalls === 1
          ? jobStatus({ status: "running", stage: "analyse", progress_pct: 50 })
          : jobStatus({ status: "done", stage: "done", progress_pct: 100, analysis_id: "a1" }),
      );
    }),
  );

  const statuses: Array<{ status: string }> = [];
  const { abort } = watchJob(
    "job-1",
    {
      authFetch: async () =>
        throwingSseResponse('event: stage\ndata: {"stage":"extract","progress_pct":10}\n\n'),
      getJob: async (id) => {
        const response = await fetch(`/api/jobs/${id}`);
        return response.json();
      },
    },
    (status) => statuses.push(status),
  );

  await vi.waitFor(() => expect(statuses.length).toBeGreaterThan(0));

  await vi.advanceTimersByTimeAsync(POLL_MS);
  await vi.waitFor(() => expect(pollCalls).toBe(1));

  await vi.advanceTimersByTimeAsync(POLL_MS);
  await vi.waitFor(() => expect(pollCalls).toBe(2));

  expect(statuses.at(-1)).toMatchObject({ status: "done" });
  abort();
});

test("watchJob stops polling and reports failed when the job is gone (404)", async () => {
  vi.useFakeTimers();
  let pollCalls = 0;
  server.use(
    http.get("/api/jobs/:id", () => {
      pollCalls += 1;
      return HttpResponse.json({ detail: "job not found" }, { status: 404 });
    }),
  );

  const statuses: Array<{ status: string; error?: string | null }> = [];
  const { abort } = watchJob(
    "job-1",
    {
      // Empty body: the stream closes immediately with no terminal event, so watchJob
      // falls straight into polling, same as a real "disconnected" result would.
      authFetch: async () => sseResponse(""),
      getJob: async (id) => {
        const response = await fetch(`/api/jobs/${id}`);
        if (!response.ok) {
          const body = (await response.json().catch(() => undefined)) as { detail?: string } | undefined;
          throw new ApiError(response.status, body?.detail ?? response.statusText);
        }
        return response.json();
      },
    },
    (status) => statuses.push(status),
  );

  await vi.advanceTimersByTimeAsync(POLL_MS);
  await vi.waitFor(() => expect(pollCalls).toBe(1));
  expect(statuses.at(-1)).toMatchObject({ status: "failed", error: "job not found" });

  // No further polls once a 404/410 is treated as terminal.
  await vi.advanceTimersByTimeAsync(POLL_MS * 3);
  expect(pollCalls).toBe(1);
  abort();
});

test("watchJob stops polling and reports failed after 5 consecutive poll failures", async () => {
  vi.useFakeTimers();
  let pollCalls = 0;
  server.use(
    http.get("/api/jobs/:id", () => {
      pollCalls += 1;
      return new HttpResponse(null, { status: 503 });
    }),
  );

  const statuses: Array<{ status: string; error?: string | null }> = [];
  const { abort } = watchJob(
    "job-1",
    {
      authFetch: async () => sseResponse(""),
      getJob: async (id) => {
        const response = await fetch(`/api/jobs/${id}`);
        if (!response.ok) throw new ApiError(response.status, response.statusText || "Server error");
        return response.json();
      },
    },
    (status) => statuses.push(status),
  );

  for (let i = 1; i <= 5; i += 1) {
    await vi.advanceTimersByTimeAsync(POLL_MS);
    await vi.waitFor(() => expect(pollCalls).toBe(i));
  }

  expect(statuses.at(-1)).toMatchObject({ status: "failed" });

  // No 6th poll: watchJob gave up after the 5th consecutive failure.
  await vi.advanceTimersByTimeAsync(POLL_MS * 2);
  expect(pollCalls).toBe(5);
  abort();
});

test("watchJob delivers no status for an SSE event that arrives after abort()", async () => {
  let unblock: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    unblock = resolve;
  });
  let delivered = false;
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (delivered) {
        controller.close();
        return;
      }
      await gate;
      delivered = true;
      controller.enqueue(
        encoder.encode('event: stage\ndata: {"stage":"extract","progress_pct":10}\n\n'),
      );
    },
  });
  const response = new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });

  const statuses: unknown[] = [];
  const { abort } = watchJob(
    "job-1",
    {
      authFetch: async () => response,
      getJob: async () => jobStatus({ status: "running" }),
    },
    (status) => statuses.push(status),
  );

  // Abort before the stream's pending read is allowed to resolve, so the "stage" frame is
  // only delivered after watchJob has already been told to stop.
  abort();
  unblock?.();
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(statuses).toEqual([]);
});
