import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { renderWithProviders } from "@/test/render";
import { ApiError } from "@/api/client";
import { server } from "@/test/msw";
import { driveConfiguredHandlers, llmEnabledHandlers } from "@/test/handlers";
import { driveFile } from "@/test/fixtures";
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

test("with coaching enabled on the server, the switch is enabled, toggling it reveals the model select, and submitting sends llm_enabled and the selected model", async () => {
  server.use(...llmEnabledHandlers());
  uploadAnalysisMock.mockResolvedValue({ job_ids: ["job-ok-1"] });

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  const coachingSwitch = await screen.findByRole("switch", { name: "Coaching" });
  expect(coachingSwitch).toBeEnabled();

  await user.click(coachingSwitch);
  await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("qwen3:8b"));

  const dropzone = screen.getByRole("button", { name: /drag and drop recordings/i });
  fireEvent.drop(dropzone, { dataTransfer: { files: [makeFile("pitch.wav")] } });
  await user.click(screen.getByRole("button", { name: "Analyse 1 file" }));

  await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalledTimes(1));
  const [, fields] = uploadAnalysisMock.mock.calls[0];
  expect(fields).toMatchObject({ llm_enabled: true, llm_model: "qwen3:8b" });
});

test("the Google Drive tab is disabled with a not-configured note when the server has no Google credentials", async () => {
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  expect(await screen.findByRole("tab", { name: "Google Drive" })).toBeDisabled();
  expect(screen.getByText("Google Drive is not configured on this server")).toBeInTheDocument();
});

test("the Google Drive tab is enabled when the server has Google credentials configured", async () => {
  server.use(...driveConfiguredHandlers());
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  await waitFor(() => expect(screen.getByRole("tab", { name: "Google Drive" })).toBeEnabled());
});

test("submitting two Drive files posts the JSON body and renders two progress rows named after the files", async () => {
  server.use(...driveConfiguredHandlers());
  server.use(
    http.get("/api/drive/files", () =>
      HttpResponse.json([
        driveFile({ id: "drive-1", name: "pitch.wav" }),
        driveFile({ id: "drive-2", name: "cold-open.wav" }),
      ]),
    ),
  );
  let capturedBody: unknown;
  server.use(
    http.post("/api/analyses", async ({ request }) => {
      capturedBody = await request.json();
      return HttpResponse.json({ job_ids: ["job-drive-1", "job-drive-2"] }, { status: 202 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  await waitFor(() => expect(screen.getByRole("tab", { name: "Google Drive" })).toBeEnabled());
  await user.click(screen.getByRole("tab", { name: "Google Drive" }));
  await user.click(await screen.findByRole("checkbox", { name: "Select pitch.wav" }));
  await user.click(await screen.findByRole("checkbox", { name: "Select cold-open.wav" }));

  await user.type(screen.getByLabelText("Speaker context"), "Real estate pitch");

  await user.click(screen.getByRole("button", { name: "Analyse 2 files" }));

  await waitFor(() =>
    expect(capturedBody).toEqual({
      source: "drive",
      file_ids: ["drive-1", "drive-2"],
      speaker_context: "Real estate pitch",
      llm: { enabled: false, model: null },
    }),
  );

  expect(await screen.findByText("Progress")).toBeInTheDocument();
  expect(screen.getAllByText("pitch.wav").length).toBeGreaterThan(0);
  expect(screen.getAllByText("cold-open.wav").length).toBeGreaterThan(0);
});

test("disables the tab triggers while a Drive submission is in flight", async () => {
  server.use(...driveConfiguredHandlers());
  server.use(
    http.get("/api/drive/files", () => HttpResponse.json([driveFile({ id: "drive-1", name: "pitch.wav" })])),
  );
  let release: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http.post("/api/analyses", async () => {
      await gate;
      return HttpResponse.json({ job_ids: ["job-drive-1"] }, { status: 202 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  await waitFor(() => expect(screen.getByRole("tab", { name: "Google Drive" })).toBeEnabled());
  await user.click(screen.getByRole("tab", { name: "Google Drive" }));
  await user.click(await screen.findByRole("checkbox", { name: "Select pitch.wav" }));
  await user.click(screen.getByRole("button", { name: "Analyse 1 file" }));

  expect(screen.getByRole("tab", { name: "Upload" })).toBeDisabled();
  expect(screen.getByRole("tab", { name: "Google Drive" })).toBeDisabled();

  release?.();

  await waitFor(() => expect(screen.getByRole("tab", { name: "Upload" })).toBeEnabled());
  expect(screen.getByRole("tab", { name: "Google Drive" })).toBeEnabled();
});

test("a 415 from the Drive submit shows the server detail inline", async () => {
  server.use(...driveConfiguredHandlers());
  server.use(
    http.get("/api/drive/files", () => HttpResponse.json([driveFile({ id: "drive-1", name: "pitch.wav" })])),
  );
  server.use(
    http.post("/api/analyses", () =>
      HttpResponse.json({ detail: "unsupported file type: pitch.wav" }, { status: 415 }),
    ),
  );

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  await waitFor(() => expect(screen.getByRole("tab", { name: "Google Drive" })).toBeEnabled());
  await user.click(screen.getByRole("tab", { name: "Google Drive" }));
  await user.click(await screen.findByRole("checkbox", { name: "Select pitch.wav" }));
  await user.click(screen.getByRole("button", { name: "Analyse 1 file" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("unsupported file type: pitch.wav");
});

test("a 409 from the Drive submit shows a Connect-Google-Drive note inline", async () => {
  server.use(...driveConfiguredHandlers());
  server.use(
    http.get("/api/drive/files", () => HttpResponse.json([driveFile({ id: "drive-1", name: "pitch.wav" })])),
  );
  server.use(
    http.post("/api/analyses", () => HttpResponse.json({ detail: "drive_not_connected" }, { status: 409 })),
  );

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  await waitFor(() => expect(screen.getByRole("tab", { name: "Google Drive" })).toBeEnabled());
  await user.click(screen.getByRole("tab", { name: "Google Drive" }));
  await user.click(await screen.findByRole("checkbox", { name: "Select pitch.wav" }));
  await user.click(screen.getByRole("button", { name: "Analyse 1 file" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Connect Google Drive in Settings");
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

test("when /llm/models is 503 the Coaching switch is disabled with the provider-unavailable text and uploads go without coaching", async () => {
  server.use(...llmEnabledHandlers());
  let modelCalls = 0;
  server.use(
    http.get("/api/llm/models", () => {
      modelCalls += 1;
      return HttpResponse.json({ detail: "LLM provider unavailable: connection refused" }, { status: 503 });
    }),
  );
  uploadAnalysisMock.mockResolvedValue({ job_ids: ["job-ok-1"] });

  const user = userEvent.setup();
  renderWithProviders(<AnalyseDrawer open onOpenChange={vi.fn()} />);

  const coachingSwitch = await screen.findByRole("switch", { name: "Coaching" });
  await waitFor(() => expect(coachingSwitch).toBeEnabled());
  expect(modelCalls).toBe(0); // the list is only fetched once coaching is switched on
  await user.click(coachingSwitch);

  expect(await screen.findByText("Coaching provider is unavailable right now")).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: "Coaching" })).toBeDisabled();
  expect(screen.getByRole("switch", { name: "Coaching" })).not.toBeChecked();
  expect(modelCalls).toBe(1);

  const dropzone = screen.getByRole("button", { name: /drag and drop recordings/i });
  fireEvent.drop(dropzone, { dataTransfer: { files: [makeFile("pitch.wav")] } });
  await user.click(screen.getByRole("button", { name: "Analyse 1 file" }));

  await waitFor(() => expect(uploadAnalysisMock).toHaveBeenCalledTimes(1));
  const [, fields] = uploadAnalysisMock.mock.calls[0];
  expect(fields).toMatchObject({ llm_enabled: false, llm_model: undefined });
});

test("after a provider 503, closing and reopening the drawer lets coaching be switched on again and refetches the models", async () => {
  server.use(...llmEnabledHandlers());
  server.use(
    http.get("/api/llm/models", () =>
      HttpResponse.json({ detail: "LLM provider unavailable: connection refused" }, { status: 503 }),
    ),
  );

  const user = userEvent.setup();
  const onOpenChange = vi.fn();
  const { rerender } = renderWithProviders(<AnalyseDrawer open onOpenChange={onOpenChange} />);

  const coachingSwitch = await screen.findByRole("switch", { name: "Coaching" });
  await waitFor(() => expect(coachingSwitch).toBeEnabled());
  await user.click(coachingSwitch);
  expect(await screen.findByText("Coaching provider is unavailable right now")).toBeInTheDocument();

  await user.keyboard("{Escape}");
  expect(onOpenChange).toHaveBeenLastCalledWith(false);
  rerender(<AnalyseDrawer open={false} onOpenChange={onOpenChange} />);

  server.use(...llmEnabledHandlers());
  rerender(<AnalyseDrawer open onOpenChange={onOpenChange} />);

  const reopenedSwitch = await screen.findByRole("switch", { name: "Coaching" });
  expect(reopenedSwitch).toBeEnabled();
  await user.click(reopenedSwitch);
  await waitFor(() => expect(screen.getByRole("combobox")).toHaveTextContent("qwen3:8b"));
  expect(screen.queryByText("Coaching provider is unavailable right now")).not.toBeInTheDocument();
});
