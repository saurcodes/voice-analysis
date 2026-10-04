import { act, screen } from "@testing-library/react";
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
