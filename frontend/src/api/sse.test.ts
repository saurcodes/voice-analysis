import { http, HttpResponse } from "msw";
import { afterEach, expect, test, vi } from "vitest";
import { server } from "@/test/msw";
import { jobStatus } from "@/test/fixtures";
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
