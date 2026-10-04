import { act, screen, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { renderWithProviders } from "@/test/render";
import { JobProgressList, type JobProgressItem } from "./JobProgressList";
import * as sse from "@/api/sse";

vi.mock("@/api/sse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/sse")>();
  return { ...actual, watchJob: vi.fn() };
});

const watchJobMock = vi.mocked(sse.watchJob);

afterEach(() => {
  watchJobMock.mockReset();
});

function mockWatchJob() {
  let emit: ((status: sse.JobStatusLike) => void) | undefined;
  const abort = vi.fn();
  watchJobMock.mockImplementation((_jobId, _deps, onStatus) => {
    emit = onStatus;
    return { abort };
  });
  return { emit: (status: sse.JobStatusLike) => act(() => emit?.(status)), abort };
}

test("shows the stage label sequence, a live progress bar, then an Open analysis link on done", () => {
  const { emit } = mockWatchJob();
  const jobs: JobProgressItem[] = [{ key: "job-1", fileName: "take-one.wav", jobId: "job-1" }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  expect(screen.getByText("take-one.wav")).toBeInTheDocument();

  emit({ status: "running", stage: "extract", progress_pct: 20 });
  expect(screen.getByText(/extracting audio/i)).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");

  emit({ status: "running", stage: "analyse", progress_pct: 55 });
  expect(screen.getByText(/analysing voice/i)).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "55");

  emit({ status: "done", analysis_id: "a-1" });
  const link = screen.getByRole("link", { name: "Open analysis" });
  expect(link).toHaveAttribute("href", "/analyses/a-1");
});

test("shows the error message and a Retry button on failure", () => {
  const { emit } = mockWatchJob();
  const jobs: JobProgressItem[] = [{ key: "job-2", fileName: "take-two.wav", jobId: "job-2" }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  emit({ status: "failed", error: "transcription backend unavailable" });

  expect(screen.getByText("transcription backend unavailable")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});

test("keeps updating from polling after an SSE timeout (running at 55 then done)", () => {
  // sse.ts's watchJob maps an SSE "timeout" event to {status: "running"} and switches to
  // polling internally; from this component's perspective that's indistinguishable from any
  // other running status update, so this just exercises the same onStatus sequence a
  // timeout-then-poll run would produce.
  const { emit } = mockWatchJob();
  const jobs: JobProgressItem[] = [{ key: "job-3", fileName: "take-three.wav", jobId: "job-3" }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  emit({ status: "running", progress_pct: 55 });
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "55");
  expect(screen.getByText(/working/i)).toBeInTheDocument();

  emit({ status: "done", analysis_id: "a-3" });
  expect(screen.getByRole("link", { name: "Open analysis" })).toBeInTheDocument();
});

test("aborts the watcher on unmount", () => {
  const { abort } = mockWatchJob();
  const jobs: JobProgressItem[] = [{ key: "job-4", fileName: "take-four.wav", jobId: "job-4" }];
  const { unmount } = renderWithProviders(<JobProgressList jobs={jobs} />);

  unmount();
  expect(abort).toHaveBeenCalled();
});

test("shows an upload progress row before a job id exists", () => {
  const jobs: JobProgressItem[] = [{ key: "job-5", fileName: "take-five.wav", uploadPct: 42 }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  expect(screen.getByText("take-five.wav")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  expect(screen.getByText(/uploading/i)).toBeInTheDocument();
  expect(watchJobMock).not.toHaveBeenCalled();
});

test("a row queued in a batch reads Waiting, without a percentage", () => {
  const jobs: JobProgressItem[] = [{ key: "job-6", fileName: "take-six.wav" }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  expect(screen.getByText("Waiting")).toBeInTheDocument();
  expect(screen.queryByText("0%")).not.toBeInTheDocument();
  expect(screen.queryByText(/uploading/i)).not.toBeInTheDocument();
});

test("a status without a stage keeps the stage already shown, and done fills the bar", () => {
  const { emit } = mockWatchJob();
  const jobs: JobProgressItem[] = [{ key: "job-7", fileName: "take-seven.wav", jobId: "job-7" }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  emit({ status: "running", stage: "transcribe", progress_pct: 60 });
  emit({ status: "running", progress_pct: 70 });
  expect(screen.getByText("Transcribing")).toBeInTheDocument();
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "70");

  emit({ status: "done", analysis_id: "a-7" });
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
});

test("a row seeded as failed is not watched", () => {
  mockWatchJob();
  const jobs: JobProgressItem[] = [
    { key: "job-8", fileName: "take-eight.wav", jobId: "job-8", error: "decoder crashed" },
  ];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  expect(screen.getByText("decoder crashed")).toBeInTheDocument();
  expect(watchJobMock).not.toHaveBeenCalled();
});

test("a terminal status refreshes the library and jobs queries", () => {
  const invalidateSpy = vi.spyOn(QueryClient.prototype, "invalidateQueries");
  const { emit } = mockWatchJob();
  const jobs: JobProgressItem[] = [{ key: "job-9", fileName: "take-nine.wav", jobId: "job-9" }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  emit({ status: "running", stage: "analyse", progress_pct: 50 });
  expect(invalidateSpy).not.toHaveBeenCalled();

  emit({ status: "done", analysis_id: "a-9" });
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["vc", "summaries"] });
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["vc", "jobs"] });
  invalidateSpy.mockRestore();
});

test("with the real watchJob over CRLF frames: Extracting audio, still Extracting audio after progress, then Done", async () => {
  const actual = await vi.importActual<typeof import("@/api/sse")>("@/api/sse");
  const encoder = new TextEncoder();
  let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      streamController = controller;
    },
  });
  const stubAuthFetch = vi.fn(
    async () =>
      new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }),
  );
  watchJobMock.mockImplementation((jobId, deps, onStatus) =>
    actual.watchJob(jobId, { ...deps, authFetch: stubAuthFetch }, onStatus),
  );

  const jobs: JobProgressItem[] = [{ key: "job-10", fileName: "take-ten.wav", jobId: "job-10" }];
  renderWithProviders(<JobProgressList jobs={jobs} />);

  await act(async () => {
    streamController?.enqueue(
      encoder.encode('event: stage\r\ndata: {"stage":"extract","progress_pct":10}\r\n\r\n'),
    );
  });
  expect(await screen.findByText("Extracting audio")).toBeInTheDocument();

  await act(async () => {
    streamController?.enqueue(
      encoder.encode('event: progress\r\ndata: {"progress_pct":25,"stage":"extract"}\r\n\r\n'),
    );
  });
  await waitFor(() =>
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25"),
  );
  expect(screen.getByText("Extracting audio")).toBeInTheDocument();

  await act(async () => {
    streamController?.enqueue(encoder.encode('event: done\r\ndata: {"analysis_id":"a-10"}\r\n\r\n'));
  });
  expect(await screen.findByText("Done")).toBeInTheDocument();
  expect(stubAuthFetch).toHaveBeenCalledWith("/api/jobs/job-10/events", expect.anything());
});
