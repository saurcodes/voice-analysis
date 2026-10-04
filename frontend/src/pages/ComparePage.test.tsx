import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router";
import { server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { comparison, summary } from "@/test/fixtures";
import { ComparePage } from "./ComparePage";

function renderPage(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/compare" element={<ComparePage />} />
    </Routes>,
    { route },
  );
}

test("fewer than two ids shows the instruction state with a Library link", () => {
  renderPage("/compare?ids=a1a1a1a1-0000-4000-8000-000000000001");

  expect(
    screen.getByText("Select two or more recordings in the Library to compare them."),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Back to Library" })).toHaveAttribute("href", "/");
});

test("no ids at all also shows the instruction state", () => {
  renderPage("/compare");

  expect(
    screen.getByText("Select two or more recordings in the Library to compare them."),
  ).toBeInTheDocument();
});

test("a single id never issues a GET /api/comparisons request", async () => {
  const comparisonsSpy = vi.fn();
  server.use(
    http.get("/api/comparisons", () => {
      comparisonsSpy();
      return HttpResponse.json(comparison());
    }),
  );

  renderPage("/compare?ids=a1a1a1a1-0000-4000-8000-000000000001");

  expect(
    screen.getByText("Select two or more recordings in the Library to compare them."),
  ).toBeInTheDocument();

  // useComparison's `enabled: ids.length >= 2` means the query never starts for a single id,
  // so this isn't a timing race; flush a tick anyway so a regression that *did* fire a
  // request would still be caught.
  await Promise.resolve();
  expect(comparisonsSpy).not.toHaveBeenCalled();
});

test("two ids loads the comparison: mismatch banner, grouped table, and default 4 trend charts", async () => {
  const data = comparison();
  server.use(http.get("/api/analyses", () => HttpResponse.json([summary(), summary({ id: data.analysis_ids[1] })])));

  renderPage(`/compare?ids=${data.analysis_ids.join(",")}`);

  // Default fixture: analyser_version_mismatch true, config_mismatch false.
  await waitFor(() =>
    expect(
      screen.getByText("Different analyser versions; numbers may differ for reasons other than your speaking."),
    ).toBeInTheDocument(),
  );
  expect(
    screen.queryByText("These recordings were analysed with different settings; deltas may not be comparable."),
  ).not.toBeInTheDocument();

  // Table rows grouped (at least Pitch and Transcript sections from the fixture).
  expect(screen.getByText("Pitch")).toBeInTheDocument();
  expect(screen.getByText("Transcript")).toBeInTheDocument();

  // Default 4 charts: 2 named defaults present in the fixture's rows (pitch.f0_range_st,
  // transcript.derived.fillers_per_min) padded with 2 more available rows to reach 4.
  const figures = screen.getAllByRole("img");
  expect(figures).toHaveLength(4);
  expect(screen.getByRole("img", { name: /Pitch range across recordings/ })).toBeInTheDocument();
});

test("picking another path adds a chart", async () => {
  const data = comparison();
  server.use(http.get("/api/analyses", () => HttpResponse.json([summary(), summary({ id: data.analysis_ids[1] })])));

  renderPage(`/compare?ids=${data.analysis_ids.join(",")}`);

  await waitFor(() => expect(screen.getAllByRole("img")).toHaveLength(4));

  // The 5th available path ("Weak syllable peaks") isn't one of the 4 selected by default
  // (the fixture's rows only overlap 2 of the 4 named defaults, padded with the other 2
  // non-default rows first - see defaultSelection() in TrendCharts.tsx).
  const chip = screen.getByRole("button", { name: "Weak syllable peaks" });
  expect(chip).toHaveAttribute("aria-pressed", "false");

  await userEvent.click(chip);

  expect(chip).toHaveAttribute("aria-pressed", "true");
  expect(screen.getAllByRole("img")).toHaveLength(5);
});

test("both mismatch banners show when the comparison has both flags set", async () => {
  const data = { ...comparison(), config_mismatch: true };
  server.use(http.get("/api/comparisons", () => HttpResponse.json(data)));
  server.use(http.get("/api/analyses", () => HttpResponse.json([summary(), summary({ id: data.analysis_ids[1] })])));

  renderPage(`/compare?ids=${data.analysis_ids.join(",")}`);

  await waitFor(() =>
    expect(
      screen.getByText("These recordings were analysed with different settings; deltas may not be comparable."),
    ).toBeInTheDocument(),
  );
  expect(
    screen.getByText("Different analyser versions; numbers may differ for reasons other than your speaking."),
  ).toBeInTheDocument();
});

test("a 404 from the comparisons endpoint shows the not-found message", async () => {
  server.use(http.get("/api/comparisons", () => new HttpResponse(JSON.stringify({ detail: "not found" }), { status: 404 })));

  renderPage("/compare?ids=a1a1a1a1-0000-4000-8000-000000000001,a1a1a1a1-0000-4000-8000-000000000002");

  await waitFor(() =>
    expect(screen.getByText("One of these recordings was not found.")).toBeInTheDocument(),
  );
  expect(screen.getByRole("link", { name: "Back to Library" })).toHaveAttribute("href", "/");
});

test("header lists recordings with a colour swatch and formatted date, in request order", async () => {
  const data = comparison();
  server.use(http.get("/api/analyses", () => HttpResponse.json([summary(), summary({ id: data.analysis_ids[1] })])));

  renderPage(`/compare?ids=${data.analysis_ids.join(",")}`);

  await waitFor(() => expect(screen.getByText("Compare recordings")).toBeInTheDocument());

  const items = within(screen.getByRole("list")).getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(items[0]).toHaveTextContent("practice-run.wav");
});
