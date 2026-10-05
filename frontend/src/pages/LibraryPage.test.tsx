import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { jobStatus, summary } from "@/test/fixtures";
import { formatDateTime, relativeTime } from "@/lib/dates";
import { LibraryPage } from "./LibraryPage";

const navigateMock = vi.fn();

vi.mock("react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router")>();
  return { ...actual, useNavigate: () => navigateMock };
});

afterEach(() => {
  navigateMock.mockReset();
});

function rowFixtures() {
  return [
    summary({
      id: "row-1",
      file_name: "practice-run.wav",
      recorded_at: "2026-09-28T14:03:00Z",
      f0_range_st: 10.84,
      flat_pct: 20.03,
      pauses_per_min: 12.0,
      fillers_per_min: 18.0,
    }),
    summary({
      id: "row-2",
      file_name: "follow-up.wav",
      recorded_at: "2026-09-30T09:15:00Z",
      f0_range_st: null,
      flat_pct: null,
      pauses_per_min: null,
      fillers_per_min: null,
      has_transcript: false,
    }),
  ];
}

test("renders analyses with numbers formatted to one decimal in mono, and null as a muted hyphen", async () => {
  server.use(http.get("/api/analyses", () => HttpResponse.json(rowFixtures())));
  server.use(http.get("/api/jobs", () => HttpResponse.json([])));

  renderWithProviders(<LibraryPage />);

  expect(await screen.findByText("practice-run.wav")).toBeInTheDocument();
  expect(screen.getByText("follow-up.wav")).toBeInTheDocument();

  const row1 = screen.getByText("practice-run.wav").closest("tr");
  expect(row1).not.toBeNull();
  const withinRow1 = within(row1 as HTMLElement);
  expect(withinRow1.getByText("10.8")).toHaveClass("num");
  expect(withinRow1.getByText("20.0")).toHaveClass("num");

  const row2 = screen.getByText("follow-up.wav").closest("tr");
  const withinRow2 = within(row2 as HTMLElement);
  const naCells = withinRow2.getAllByLabelText("not available");
  expect(naCells.length).toBeGreaterThan(0);
  for (const cell of naCells) expect(cell).toHaveTextContent("-");
});

test("the relative Recorded time is keyboard-focusable and reveals the exact date on focus", async () => {
  server.use(http.get("/api/analyses", () => HttpResponse.json(rowFixtures())));
  server.use(http.get("/api/jobs", () => HttpResponse.json([])));

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);
  await screen.findByText("practice-run.wav");

  const exact = formatDateTime("2026-09-28T14:03:00Z");
  expect(screen.queryByText(exact)).not.toBeInTheDocument();

  // Tab from the row's checkbox lands on the Recorded trigger (the file name is not focusable).
  screen.getByRole("checkbox", { name: "Select practice-run.wav" }).focus();
  await user.tab();
  expect(document.activeElement).toHaveTextContent(relativeTime("2026-09-28T14:03:00Z"));
  expect((await screen.findAllByText(exact)).length).toBeGreaterThan(0);
});

test("shows the empty state with an Analyse CTA when there are no analyses", async () => {
  server.use(http.get("/api/analyses", () => HttpResponse.json([])));
  server.use(http.get("/api/jobs", () => HttpResponse.json([])));

  renderWithProviders(<LibraryPage />);

  expect(await screen.findByText(/upload a recording to get your first analysis/i)).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Analyse" }).length).toBeGreaterThan(0);
});

test("delete flow: confirm calls DELETE, the row disappears, and its id drops out of the selection", async () => {
  // A mutable backing list: useDeleteAnalysis's onSuccess invalidates ["vc","summaries"],
  // which triggers a real refetch of GET /api/analyses, so that handler has to actually
  // reflect the delete for the row to disappear (a static fixture would just come back).
  let rows = [
    ...rowFixtures(),
    summary({ id: "row-3", file_name: "third-take.wav", recorded_at: "2026-10-01T09:00:00Z" }),
  ];
  server.use(http.get("/api/analyses", () => HttpResponse.json(rows)));
  server.use(http.get("/api/jobs", () => HttpResponse.json([])));
  let deleteCalledWith: string | undefined;
  server.use(
    http.delete("/api/analyses/:id", ({ params }) => {
      deleteCalledWith = params.id as string;
      rows = rows.filter((row) => row.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);

  await screen.findByText("practice-run.wav");
  const compareButton = screen.getByRole("button", { name: "Compare" });

  // Select the row we're about to delete, plus one other, so Compare is enabled going in.
  await user.click(screen.getByRole("checkbox", { name: "Select practice-run.wav" }));
  await user.click(screen.getByRole("checkbox", { name: "Select follow-up.wav" }));
  expect(compareButton).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "Delete practice-run.wav" }));

  expect(await screen.findByText("Delete this analysis?")).toBeInTheDocument();
  expect(screen.getByText("This cannot be undone.")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Delete" }));

  await waitFor(() => expect(screen.queryByText("practice-run.wav")).not.toBeInTheDocument());
  expect(deleteCalledWith).toBe("row-1");
  expect(screen.getByText("follow-up.wav")).toBeInTheDocument();

  // The deleted row's id is gone from selection: only one row (follow-up.wav) is still
  // selected, so Compare is disabled again.
  expect(compareButton).toBeDisabled();

  // Selecting a third row re-enables Compare, and the deleted id never reappears in the
  // navigate target.
  await user.click(screen.getByRole("checkbox", { name: "Select third-take.wav" }));
  expect(compareButton).toBeEnabled();
  await user.click(compareButton);
  expect(navigateMock).toHaveBeenCalledWith("/compare?ids=row-2,row-3");
});

test("Compare is disabled until two rows are selected, then navigates with ids in selection order", async () => {
  server.use(http.get("/api/analyses", () => HttpResponse.json(rowFixtures())));
  server.use(http.get("/api/jobs", () => HttpResponse.json([])));

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);

  await screen.findByText("practice-run.wav");
  const compareButton = screen.getByRole("button", { name: "Compare" });
  expect(compareButton).toBeDisabled();

  await user.click(screen.getByRole("checkbox", { name: "Select follow-up.wav" }));
  expect(compareButton).toBeDisabled();

  await user.click(screen.getByRole("checkbox", { name: "Select practice-run.wav" }));
  expect(compareButton).toBeEnabled();

  await user.click(compareButton);
  expect(navigateMock).toHaveBeenCalledWith("/compare?ids=row-2,row-1");
});

test("a failed job row shows Retry, which POSTs a retry and switches the row onto the new job", async () => {
  const failedJob = jobStatus({
    id: "job-failed-1",
    status: "failed",
    stage: "transcribe",
    error: "transcription backend unavailable",
    file_name: "noisy-call.wav",
  });
  const newJob = jobStatus({
    id: "job-new-1",
    status: "running",
    stage: "analyse",
    progress_pct: 40,
    error: null,
    file_name: "noisy-call.wav",
  });
  let retried = false;
  server.use(http.get("/api/analyses", () => HttpResponse.json([])));
  // After the retry the server lists both: the old failed job and the new running one.
  server.use(
    http.get("/api/jobs", () => HttpResponse.json(retried ? [failedJob, newJob] : [failedJob])),
  );
  const watchedIds: string[] = [];
  server.use(
    http.get("/api/jobs/:id/events", ({ params }) => {
      watchedIds.push(params.id as string);
      return new HttpResponse('event: stage\r\ndata: {"stage":"analyse","progress_pct":40}\r\n\r\n', {
        status: 200,
        headers: { "content-type": "text/event-stream" },
      });
    }),
  );
  server.use(http.get("/api/jobs/:id", () => HttpResponse.json(newJob)));
  let retriedId: string | undefined;
  server.use(
    http.post("/api/jobs/:id/retry", ({ params }) => {
      retriedId = params.id as string;
      retried = true;
      return HttpResponse.json({ job_id: "job-new-1" }, { status: 202 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);

  expect(await screen.findByText("transcription backend unavailable")).toBeInTheDocument();
  // A row the jobs list already reports as failed is not watched.
  expect(watchedIds).toEqual([]);

  await user.click(screen.getByRole("button", { name: "Retry" }));

  await waitFor(() => expect(retriedId).toBe("job-failed-1"));
  expect(await screen.findByText("Analysing voice")).toBeInTheDocument();
  expect(screen.queryByText("transcription backend unavailable")).not.toBeInTheDocument();
  expect(watchedIds).toEqual(["job-new-1"]);
  // The new job is shown once, in the swapped row, not as a second row.
  await waitFor(() => expect(screen.getAllByText("noisy-call.wav")).toHaveLength(1));
});

test("the library paginates in pages of 50 via Load more, hiding it once the pages are exhausted", async () => {
  const page1 = Array.from({ length: 50 }, (_, i) => summary({ id: `p1-${i}`, file_name: `rec-${i}.wav` }));
  const page2 = [summary({ id: "p2-0", file_name: "last-one.wav" })];
  server.use(
    http.get("/api/analyses", ({ request }) => {
      const offset = Number(new URL(request.url).searchParams.get("offset") ?? "0");
      return HttpResponse.json(offset === 0 ? page1 : page2);
    }),
  );
  server.use(http.get("/api/jobs", () => HttpResponse.json([])));

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);

  await screen.findByText("rec-0.wav");
  expect(screen.queryByText("last-one.wav")).not.toBeInTheDocument();

  await user.click(screen.getByRole("checkbox", { name: "Select rec-0.wav" }));
  await user.click(screen.getByRole("button", { name: "Load more" }));

  await screen.findByText("last-one.wav");
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  // The earlier selection survives the extra page loading in.
  expect(screen.getByRole("checkbox", { name: "Select rec-0.wav" })).toBeChecked();
});

test("dismissing a failed job calls DELETE and removes the row", async () => {
  const failedJob = jobStatus({
    id: "job-dismiss-1",
    status: "failed",
    error: "decoder crashed",
    file_name: "bad-take.wav",
  });
  let jobs = [failedJob];
  server.use(http.get("/api/analyses", () => HttpResponse.json([])));
  server.use(http.get("/api/jobs", () => HttpResponse.json(jobs)));
  let deletedId: string | undefined;
  server.use(
    http.delete("/api/jobs/:id", ({ params }) => {
      deletedId = params.id as string;
      jobs = jobs.filter((job) => job.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);

  expect(await screen.findByText("decoder crashed")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Dismiss" }));

  await waitFor(() => expect(deletedId).toBe("job-dismiss-1"));
  await waitFor(() => expect(screen.queryByText("decoder crashed")).not.toBeInTheDocument());
});

test("a retry the server refuses (410) shows its detail inline", async () => {
  const failedJob = jobStatus({
    id: "job-failed-2",
    status: "failed",
    stage: "extract",
    error: "decoder crashed",
    file_name: "old-call.wav",
  });
  server.use(http.get("/api/analyses", () => HttpResponse.json([])));
  server.use(http.get("/api/jobs", () => HttpResponse.json([failedJob])));
  server.use(
    http.post("/api/jobs/:id/retry", () =>
      HttpResponse.json(
        { detail: "the uploaded file is no longer stored; upload it again" },
        { status: 410 },
      ),
    ),
  );

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);

  expect(await screen.findByText("decoder crashed")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Retry" }));

  expect(
    await screen.findByText(/the uploaded file is no longer stored; upload it again/),
  ).toBeInTheDocument();
});
