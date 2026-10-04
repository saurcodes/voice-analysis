import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/render";
import { ApiError } from "@/api/client";
import { AnalyseDrawer } from "./AnalyseDrawer";
import * as uploadModule from "@/api/upload";

vi.mock("@/api/upload", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/upload")>();
  return { ...actual, uploadAnalysis: vi.fn() };
});

const uploadAnalysisMock = vi.mocked(uploadModule.uploadAnalysis);

function makeFile(name: string, type = "audio/wav"): File {
  return new File(["x".repeat(16)], name, { type });
}

afterEach(() => {
  uploadAnalysisMock.mockReset();
});

test("rejects an unsupported extension client-side, uploads the rest, shows a 413 inline, and the other file reaches done", async () => {
  let callCount = 0;
  uploadAnalysisMock.mockImplementation(async () => {
    callCount += 1;
    if (callCount === 2) throw new ApiError(413, "File too large");
    return { job_ids: ["job-ok-1"] };
  });

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  // A real browser's <input accept="..."> filters the file picker dialog itself, so the
  // client-side "unsupported type" rejection only ever has something to reject when files
  // arrive via drag-and-drop, which isn't accept-filtered. Dropping onto the dropzone
  // (role="button") is what exercises UploadDropzone's own addFiles() filtering.
  const dropzone = screen.getByRole("button", { name: /drag and drop recordings/i });
  fireEvent.drop(dropzone, {
    dataTransfer: { files: [makeFile("take-one.wav"), makeFile("take-two.mp3"), makeFile("notes.txt", "text/plain")] },
  });

  expect(screen.getByText(/unsupported file type/i)).toBeInTheDocument();
  expect(screen.getByText("take-one.wav")).toBeInTheDocument();
  expect(screen.getByText("take-two.mp3")).toBeInTheDocument();

  await user.type(screen.getByLabelText("Speaker context"), "Real estate pitch");

  await user.click(screen.getByRole("button", { name: "Analyse 2 files" }));

  await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalledTimes(2));

  expect(await screen.findByText("File too large")).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: "Open analysis" })).toBeInTheDocument();
});

test("the Coaching switch is disabled with an explanation when the server has it off", async () => {
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  expect(await screen.findByText("Coaching is not enabled on this server yet")).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "Coaching" })).toBeDisabled();
});

test("the Google Drive tab is disabled", () => {
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  expect(screen.getByRole("tab", { name: "Google Drive" })).toBeDisabled();
});

test("a 415 from the server shows its detail inline on that file's row", async () => {
  uploadAnalysisMock.mockRejectedValue(new ApiError(415, "unsupported media type: video/x-ms-asf"));

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  const dropzone = screen.getByRole("button", { name: /drag and drop recordings/i });
  fireEvent.drop(dropzone, { dataTransfer: { files: [makeFile("odd-take.wav")] } });
  await user.click(screen.getByRole("button", { name: "Analyse 1 file" }));

  expect(await screen.findByText("unsupported media type: video/x-ms-asf")).toBeInTheDocument();
});

test("reports each job as it is created, blocks closing mid-batch, then clears the picked files", async () => {
  let releaseSecond: (() => void) | undefined;
  const secondGate = new Promise<void>((resolve) => {
    releaseSecond = resolve;
  });
  let callCount = 0;
  uploadAnalysisMock.mockImplementation(async () => {
    callCount += 1;
    if (callCount === 2) {
      await secondGate;
      return { job_ids: ["job-b"] };
    }
    return { job_ids: ["job-a"] };
  });
  const onJobsCreated = vi.fn();
  const onOpenChange = vi.fn();

  const user = userEvent.setup();
  renderWithProviders(
    <AnalyseDrawer open onOpenChange={onOpenChange} onJobsCreated={onJobsCreated} />,
  );

  const dropzone = screen.getByRole("button", { name: /drag and drop recordings/i });
  fireEvent.drop(dropzone, {
    dataTransfer: { files: [makeFile("first.wav"), makeFile("second.wav")] },
  });
  await user.click(screen.getByRole("button", { name: "Analyse 2 files" }));

  // The first job is reported before the second upload finishes.
  await waitFor(() => expect(onJobsCreated).toHaveBeenCalledWith(["job-a"]));
  expect(onJobsCreated).toHaveBeenCalledTimes(1);

  expect(screen.getByText("Uploads in progress")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  await user.keyboard("{Escape}");
  expect(onOpenChange).not.toHaveBeenCalledWith(false);

  releaseSecond?.();
  await waitFor(() => expect(onJobsCreated).toHaveBeenCalledWith(["job-b"]));

  // The batch is done: the picker is empty again, the progress rows stay.
  expect(await screen.findByRole("button", { name: "Analyse 0 files" })).toBeDisabled();
  expect(screen.queryByText("Uploads in progress")).not.toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: /first\.wav/ })).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: /second\.wav/ })).toBeInTheDocument();
});

test("the submit button is disabled until a file is added", () => {
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  expect(screen.getByRole("button", { name: "Analyse 0 files" })).toBeDisabled();
});
