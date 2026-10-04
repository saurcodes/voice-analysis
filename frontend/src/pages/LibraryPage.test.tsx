import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { jobStatus, summary } from "@/test/fixtures";
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

test("a failed job row shows Retry, which POSTs a retry", async () => {
  const failedJob = jobStatus({
    id: "job-failed-1",
    status: "failed",
    stage: "transcribe",
    error: "transcription backend unavailable",
    file_name: "noisy-call.wav",
  });
  server.use(http.get("/api/analyses", () => HttpResponse.json([])));
  server.use(http.get("/api/jobs", () => HttpResponse.json([failedJob])));
  // No SSE body (204, no content): JobProgressList's watchJob falls straight through to
  // polling GET /api/jobs/:id below, which is what actually reports the failed status here.
  server.use(http.get("/api/jobs/:id/events", () => new HttpResponse(null, { status: 204 })));
  server.use(http.get("/api/jobs/:id", () => HttpResponse.json(failedJob)));
  let retriedId: string | undefined;
  server.use(
    http.post("/api/jobs/:id/retry", ({ params }) => {
      retriedId = params.id as string;
      return HttpResponse.json({ job_id: params.id as string }, { status: 202 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<LibraryPage />);

  expect(await screen.findByText("transcription backend unavailable")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Retry" }));

  await waitFor(() => expect(retriedId).toBe("job-failed-1"));
});
