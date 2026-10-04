/**
 * Fetch-based SSE client for job progress. Native EventSource can't send an Authorization
 * header, and Keycloak access tokens only last ~300s, so streamJobEvents() parses
 * text/event-stream frames off a plain fetch() Response's ReadableStream instead.
 *
 * watchJob() orchestrates the full lifecycle a job-progress UI needs: start the SSE stream,
 * and when it ends without a terminal event (network drop, server-side "timeout", or the
 * stream just closing) fall back to polling GET /api/jobs/{id} every POLL_MS until the job
 * reaches a terminal status or the caller aborts.
 */

import { ApiError } from "./client";

export type JobEventName = "stage" | "progress" | "done" | "error" | "timeout";

export interface JobEvent {
  event: JobEventName;
  data: Record<string, unknown>;
}

export type StreamResult = "done" | "error" | "timeout" | "aborted" | "disconnected";

type TerminalEventName = "done" | "error" | "timeout";

const TERMINAL_EVENTS: ReadonlySet<JobEventName> = new Set<JobEventName>(["done", "error", "timeout"]);

function isTerminalEventName(value: JobEventName): value is TerminalEventName {
  return TERMINAL_EVENTS.has(value);
}

function isJobEventName(value: string): value is JobEventName {
  return (
    value === "stage" ||
    value === "progress" ||
    value === "done" ||
    value === "error" ||
    value === "timeout"
  );
}

/**
 * Parses one blank-line-delimited SSE frame. A frame with no "event:" line is a plain
 * "message" event per the spec; this client has no use for those, so it's ignored rather
 * than passed to onEvent. "data:" may appear on multiple lines; those are joined with "\n"
 * before JSON-parsing, per the SSE spec. Lines are expected to already have any trailing
 * "\r" stripped (streamJobEvents normalises CRLF before splitting into frames); a per-line
 * strip is kept here too as a harmless defensive fallback.
 */
function handleFrame(frame: string, onEvent: (event: JobEvent) => void): TerminalEventName | undefined {
  let eventName: string | undefined;
  const dataLines: string[] = [];

  for (const rawLine of frame.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }

  if (!eventName || !isJobEventName(eventName)) return undefined;

  let data: Record<string, unknown> = {};
  const raw = dataLines.join("\n");
  if (raw) {
    try {
      data = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      data = {};
    }
  }

  onEvent({ event: eventName, data });
  return isTerminalEventName(eventName) ? eventName : undefined;
}

export interface StreamJobEventsOptions {
  authFetch: (path: string, init?: RequestInit) => Promise<Response>;
  signal?: AbortSignal;
  onEvent: (event: JobEvent) => void;
}

/**
 * Opens GET /api/jobs/{id}/events and parses frames off the body until a terminal event
 * ("done" | "error" | "timeout") arrives, the body ends, or the read fails. Resolves:
 * - the terminal event's name, once seen
 * - "aborted" if the caller's signal was aborted
 * - "disconnected" for anything else (non-2xx response, no body, stream ended or threw
 *   without a terminal event) - callers fall back to polling rather than treating this as
 *   a real failure, since a dropped connection says nothing about the job itself.
 *
 * The backend (sse-starlette 3.x) terminates lines and frames with CRLF ("\r\n"), not the
 * bare "\n" the SSE spec's examples use, so every "\r\n" in the accumulated buffer is
 * normalised to "\n" before frame boundaries are found. This runs on the whole buffer after
 * every chunk (not just the newly-appended bytes), so a terminator split across two chunks
 * right between its "\r" and "\n" - a lone "\r" left dangling at the end of the buffer until
 * the next chunk's leading "\n" arrives - still normalises correctly once both halves are in.
 */
export async function streamJobEvents(
  jobId: string,
  { authFetch, signal, onEvent }: StreamJobEventsOptions,
): Promise<StreamResult> {
  try {
    const response = await authFetch(`/api/jobs/${jobId}/events`, { signal });
    if (!response.ok || !response.body) return "disconnected";

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");

      let sepIndex = buffer.indexOf("\n\n");
      while (sepIndex !== -1) {
        const frame = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        const terminal = handleFrame(frame, onEvent);
        if (terminal) return terminal;
        sepIndex = buffer.indexOf("\n\n");
      }
    }

    return "disconnected";
  } catch {
    return signal?.aborted ? "aborted" : "disconnected";
  }
}

/** Polling cadence once SSE gives up (timeout or disconnect) but the job isn't terminal yet. */
export const POLL_MS = 2000;

/** The subset of JobStatus that watchJob can report, whether sourced from an SSE frame or a poll. */
export interface JobStatusLike {
  status: string;
  stage?: string;
  progress_pct?: number;
  error?: string | null;
  analysis_id?: string | null;
}

export interface WatchJobDeps {
  authFetch: (path: string, init?: RequestInit) => Promise<Response>;
  getJob: (id: string) => Promise<JobStatusLike>;
}

function isTerminalStatus(status: JobStatusLike): boolean {
  return status.status === "done" || status.status === "failed";
}

function mapEventToStatus(event: JobEvent): JobStatusLike {
  switch (event.event) {
    case "stage":
      return {
        status: "running",
        stage: event.data.stage as string | undefined,
        progress_pct: event.data.progress_pct as number | undefined,
      };
    case "progress":
      return {
        status: "running",
        progress_pct: event.data.progress_pct as number | undefined,
      };
    case "done":
      return {
        status: "done",
        analysis_id: event.data.analysis_id as string | undefined,
      };
    case "error":
      return {
        status: "failed",
        error: (event.data.message as string | undefined) ?? "Job failed",
      };
    case "timeout":
      // The SSE connection gave up, not the job: report "running" so the UI keeps showing
      // progress while watchJob switches to polling for the real outcome.
      return { status: "running" };
  }
}

/**
 * Watches a job end to end: SSE first, falling back to POLL_MS polling when the stream
 * times out or disconnects, until a terminal status or an explicit abort() call. onStatus
 * fires for every SSE event and every poll result, each mapped to the same JobStatusLike
 * shape, so a caller can render one progress UI regardless of which transport produced it.
 */
/** Give up polling (and report a terminal "failed" status) after this many bad polls in a row. */
const MAX_CONSECUTIVE_POLL_FAILURES = 5;

export function watchJob(
  jobId: string,
  deps: WatchJobDeps,
  onStatus: (status: JobStatusLike) => void,
): { abort: () => void } {
  const controller = new AbortController();
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let aborted = false;
  let consecutiveFailures = 0;

  function schedulePoll() {
    if (aborted) return;
    pollTimer = setTimeout(() => void poll(), POLL_MS);
  }

  async function poll() {
    if (aborted) return;
    try {
      const status = await deps.getJob(jobId);
      if (aborted) return;
      consecutiveFailures = 0;
      onStatus(status);
      if (!isTerminalStatus(status)) schedulePoll();
    } catch (error) {
      if (aborted) return;
      // The job itself is gone (deleted, or its upload expired): polling further can't
      // recover, so stop and report it as failed rather than retrying forever.
      if (error instanceof ApiError && (error.status === 404 || error.status === 410)) {
        const detail = typeof error.detail === "string" ? error.detail : "Job not found";
        onStatus({ status: "failed", error: detail });
        return;
      }
      consecutiveFailures += 1;
      if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
        const message = error instanceof Error ? error.message : "Job status unavailable";
        onStatus({ status: "failed", error: message });
        return;
      }
      schedulePoll();
    }
  }

  async function run() {
    const result = await streamJobEvents(jobId, {
      authFetch: deps.authFetch,
      signal: controller.signal,
      onEvent: (event) => {
        if (aborted) return;
        onStatus(mapEventToStatus(event));
      },
    });
    if (aborted || result === "aborted" || result === "done" || result === "error") return;
    // "timeout" or "disconnected": the stream gave up, not the job. Poll for the real status.
    schedulePoll();
  }

  void run();

  return {
    abort() {
      aborted = true;
      controller.abort();
      if (pollTimer !== undefined) clearTimeout(pollTimer);
    },
  };
}
