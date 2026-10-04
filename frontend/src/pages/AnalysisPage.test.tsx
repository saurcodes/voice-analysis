import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/msw";
import { renderWithProviders } from "@/test/render";
import { analysisDetail } from "@/test/fixtures";
import { AnalysisPage } from "./AnalysisPage";

const ANALYSIS_ID = "c3c3c3c3-0000-4000-8000-000000000001";

function renderPage(route = `/analyses/${ANALYSIS_ID}`) {
  return renderWithProviders(
    <Routes>
      <Route path="/analyses/:id" element={<AnalysisPage />} />
    </Routes>,
    { route },
  );
}

function cardFor(label: string): HTMLElement {
  const labelEl = screen.getByText(label);
  const card = labelEl.closest('[data-slot="card"]');
  if (!card) throw new Error(`No card found for label "${label}"`);
  return card as HTMLElement;
}

/** The default fixture with recording_quality.low_confidence and articulation.low_confidence
 * forced to specific values, everything else unchanged. */
function detailWithConfidence(recordingLowConfidence: boolean, articulationLowConfidence: boolean) {
  const base = analysisDetail();
  return analysisDetail("default", {
    metrics: {
      ...base.metrics,
      recording_quality: { ...base.metrics.recording_quality, low_confidence: recordingLowConfidence },
      articulation: { ...base.metrics.articulation, low_confidence: articulationLowConfidence },
    },
  });
}

beforeEach(() => {
  // jsdom has no object-URL implementation; RawPanel's download flow needs these to exist.
  URL.createObjectURL = vi.fn(() => "blob:mock-url");
  URL.revokeObjectURL = vi.fn();
});

describe("AnalysisPage", () => {
  it("renders 8 summary cards with formatted values, and 6 low-confidence badges when only recording_quality is low confidence", async () => {
    const detail = detailWithConfidence(true, false);
    server.use(http.get("/api/analyses/:id", () => HttpResponse.json(detail)));

    renderPage();

    expect(await screen.findByText("practice-run.wav")).toBeInTheDocument();

    expect(within(cardFor("Median pitch")).getByText("165")).toHaveClass("num");
    expect(within(cardFor("Pitch range")).getByText("10.8")).toHaveClass("num");
    expect(within(cardFor("Flat endings")).getByText("20.0")).toHaveClass("num");
    expect(within(cardFor("Pauses per minute")).getByText("12.0")).toHaveClass("num");
    expect(within(cardFor("Articulation rate")).getByText("3.1")).toHaveClass("num");
    expect(within(cardFor("Trailing off")).getByText("1")).toHaveClass("num");
    expect(within(cardFor("Fillers per minute")).getByText("18.0")).toHaveClass("num");
    expect(within(cardFor("Eaten words")).getByText("6.3")).toHaveClass("num");

    // recording_quality.low_confidence covers every acoustic-metric card (6); Articulation
    // rate and Eaten words key off articulation.low_confidence instead, which is false here.
    expect(screen.getAllByText("low confidence")).toHaveLength(6);
    expect(within(cardFor("Median pitch")).getByText("low confidence")).toBeInTheDocument();
    expect(within(cardFor("Pitch range")).getByText("low confidence")).toBeInTheDocument();
    expect(within(cardFor("Flat endings")).getByText("low confidence")).toBeInTheDocument();
    expect(within(cardFor("Pauses per minute")).getByText("low confidence")).toBeInTheDocument();
    expect(within(cardFor("Trailing off")).getByText("low confidence")).toBeInTheDocument();
    expect(within(cardFor("Fillers per minute")).getByText("low confidence")).toBeInTheDocument();
    expect(within(cardFor("Articulation rate")).queryByText("low confidence")).not.toBeInTheDocument();
    expect(within(cardFor("Eaten words")).queryByText("low confidence")).not.toBeInTheDocument();
  });

  it("shows a low-confidence badge on all 8 cards when both recording_quality and articulation are low confidence", async () => {
    const detail = detailWithConfidence(true, true);
    server.use(http.get("/api/analyses/:id", () => HttpResponse.json(detail)));

    renderPage();

    expect(await screen.findByText("practice-run.wav")).toBeInTheDocument();
    expect(screen.getAllByText("low confidence")).toHaveLength(8);
  });

  it("shows the quality banner, dashes for every card, and the timeline empty state for too_short", async () => {
    server.use(
      http.get("/api/analyses/:id", () => HttpResponse.json(analysisDetail("too_short"))),
    );

    renderPage();

    expect(
      await screen.findByText("Recording shorter than 2 seconds; no metrics computed."),
    ).toBeInTheDocument();

    // Nullable fields (pitch/intonation/pace blocks, and anything sourced from the
    // transcript, which is null outright for too_short) render "-".
    expect(within(cardFor("Median pitch")).getByText("-")).toBeInTheDocument();
    expect(within(cardFor("Pitch range")).getByText("-")).toBeInTheDocument();
    expect(within(cardFor("Flat endings")).getByText("-")).toBeInTheDocument();
    expect(within(cardFor("Articulation rate")).getByText("-")).toBeInTheDocument();
    expect(within(cardFor("Fillers per minute")).getByText("-")).toBeInTheDocument();
    expect(within(cardFor("Eaten words")).getByText("-")).toBeInTheDocument();
    // phrasing.pauses_per_min and energy.trailing_off_count are non-nullable counts that
    // are genuinely 0 when no speech was detected, not "unavailable" - they render 0, not
    // a dash, which is the honest answer rather than a forced placeholder.
    expect(within(cardFor("Pauses per minute")).getByText("0.0")).toBeInTheDocument();
    expect(within(cardFor("Trailing off")).getByText("0")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    expect(await screen.findByText("Not enough voiced speech for a timeline.")).toBeInTheDocument();
  });

  it("switches tabs", async () => {
    server.use(http.get("/api/analyses/:id", () => HttpResponse.json(analysisDetail("default"))));
    renderPage();

    await screen.findByText("practice-run.wav");
    expect(screen.getByRole("tab", { name: "Summary" })).toHaveAttribute("data-state", "active");

    await userEvent.click(screen.getByRole("tab", { name: "Transcript" }));
    expect(await screen.findByText("Filler word")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Transcript" })).toHaveAttribute("data-state", "active");
  });

  it("shows the config hash without its sha256: prefix", async () => {
    server.use(http.get("/api/analyses/:id", () => HttpResponse.json(analysisDetail("default"))));
    renderPage();

    expect(await screen.findByText(/\/ b60fb688$/)).toBeInTheDocument();
    expect(screen.queryByText(/sha256:/)).not.toBeInTheDocument();
  });

  it("triggers a fetch to /raw/metrics when the Metrics download button is clicked, then revokes the object URL", async () => {
    server.use(http.get("/api/analyses/:id", () => HttpResponse.json(analysisDetail("default"))));
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    // jsdom cannot navigate to a blob: URL; stub the anchor click the download relies on.
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    renderPage();
    await screen.findByText("practice-run.wav");

    await userEvent.click(screen.getByRole("tab", { name: "Raw" }));
    const metricsRow = screen.getByText("Metrics").closest("div")?.parentElement as HTMLElement;
    await userEvent.click(within(metricsRow).getByRole("button", { name: "Download" }));

    await waitFor(() => {
      const called = fetchSpy.mock.calls.some((call) => String(call[0]).includes("/raw/metrics"));
      expect(called).toBe(true);
    });
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock-url"));

    clickSpy.mockRestore();
    fetchSpy.mockRestore();
  });

  it("shows the coaching-unavailable state with warnings when coaching is null", async () => {
    server.use(
      http.get("/api/analyses/:id", () =>
        HttpResponse.json(analysisDetail("default", { coaching_warnings: ["low confidence recording"] })),
      ),
    );
    renderPage();
    await screen.findByText("practice-run.wav");

    await userEvent.click(screen.getByRole("tab", { name: "Coaching" }));
    expect(await screen.findByText("Coaching is not available yet.")).toBeInTheDocument();
    expect(screen.getByText("low confidence recording")).toBeInTheDocument();
  });

  it("shows a not-found state for a 404", async () => {
    server.use(
      http.get("/api/analyses/:id", () => HttpResponse.json({ detail: "not found" }, { status: 404 })),
    );
    renderPage();

    expect(await screen.findByText("This analysis was not found.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Library" })).toBeInTheDocument();
  });
});
