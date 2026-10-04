import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw";
import { llmEnabledHandlers } from "@/test/handlers";
import { analysisDetail, coaching } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import type { components } from "@/api/types";
import { CoachingPanel } from "./CoachingPanel";

const ANALYSIS_ID = "c3c3c3c3-0000-4000-8000-000000000001";

type AnalysisDetail = components["schemas"]["AnalysisDetail"];

function renderPanel(
  overrides: Partial<React.ComponentProps<typeof CoachingPanel>> = {},
) {
  return renderWithProviders(
    <CoachingPanel
      analysisId={ANALYSIS_ID}
      coaching={null}
      coachingWarnings={null}
      speakerContext={null}
      {...overrides}
    />,
  );
}

/**
 * Like AnalysisPage, but trimmed to just the Coaching tab: subscribes to the same
 * ["vc","analysis",id] query key useAnalysis() does and passes its fields straight through,
 * so a successful re-run (which writes into that cache entry via setQueryData) re-renders
 * CoachingPanel with the new coaching the same way it would inside the real page.
 */
function CoachingHarness({ initial }: { initial: AnalysisDetail }) {
  const query = useQuery({
    queryKey: ["vc", "analysis", initial.id] as const,
    queryFn: () => Promise.resolve(initial),
    initialData: initial,
  });
  const detail = query.data;
  return (
    <CoachingPanel
      analysisId={detail.id}
      coaching={detail.coaching}
      coachingWarnings={detail.coaching_warnings}
      speakerContext={detail.speaker_context}
    />
  );
}

function renderHarness(initial: AnalysisDetail) {
  return renderWithProviders(<CoachingHarness initial={initial} />);
}

test("the Re-run coaching button is disabled with an explanation when the server has coaching off", async () => {
  renderPanel();

  expect(await screen.findByText("Coaching is not enabled on this server yet")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Re-run coaching" })).toBeDisabled();
});

test("the Re-run coaching button stays disabled while /api/me is still loading", () => {
  server.use(http.get("/api/me", async () => new Promise(() => {})));
  renderPanel();

  expect(screen.getByRole("button", { name: "Re-run coaching" })).toBeDisabled();
  expect(screen.queryByText("Coaching is not enabled on this server yet")).not.toBeInTheDocument();
});

test("renders every coaching list, the marked-up example, and the Checks warning", async () => {
  renderPanel({
    coaching: coaching(),
    coachingWarnings: ["number 17.5 in what_is_lacking does not match any metric value"],
  });

  expect(await screen.findByText("What improved")).toBeInTheDocument();
  expect(screen.getByText(/Pitch range widened to 10.8 semitones/)).toBeInTheDocument();
  expect(screen.getByText("What is lacking")).toBeInTheDocument();
  expect(screen.getByText(/Filler words still run high at 18.0 per minute/)).toBeInTheDocument();
  expect(screen.getByText("Next steps")).toBeInTheDocument();
  expect(screen.getByText(/Cut the scripted filler phrase/)).toBeInTheDocument();

  const example = screen.getByText(/quarterly RESULTS today/);
  expect(example.tagName).toBe("PRE");
  expect(example).toHaveClass("num");

  expect(screen.getByText("Checks")).toBeInTheDocument();
  expect(
    screen.getByText("number 17.5 in what_is_lacking does not match any metric value"),
  ).toBeInTheDocument();
});

test("opens the re-run dialog with the speaker context prefilled and the model list, then posts and shows the new coaching", async () => {
  server.use(...llmEnabledHandlers());
  let capturedBody: unknown;
  server.use(
    http.post("/api/analyses/:id/coach", async ({ request, params }) => {
      capturedBody = await request.json();
      return HttpResponse.json(
        analysisDetail("default", {
          id: params.id as string,
          coaching: coaching(),
          coaching_warnings: null,
        }),
      );
    }),
  );

  const user = userEvent.setup();
  renderHarness(analysisDetail("default", { id: ANALYSIS_ID, speaker_context: "Real estate sales pitch" }));

  await waitFor(() => expect(screen.getByRole("button", { name: "Re-run coaching" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Re-run coaching" }));

  expect(screen.getByRole("heading", { name: "Re-run coaching" })).toBeInTheDocument();
  const contextField = screen.getByLabelText("Speaker context") as HTMLTextAreaElement;
  expect(contextField.value).toBe("Real estate sales pitch");

  await waitFor(() => expect(screen.getByLabelText("Model")).toHaveTextContent("qwen3:8b"));

  await user.click(screen.getByRole("button", { name: "Run" }));

  await waitFor(() =>
    expect(capturedBody).toEqual({ speaker_context: "Real estate sales pitch", model: "qwen3:8b" }),
  );

  await waitFor(() => expect(screen.queryByRole("heading", { name: "Re-run coaching" })).not.toBeInTheDocument());
  expect(await screen.findByText("What improved")).toBeInTheDocument();
});

test("a disallowed model (422) shows an inline alert and keeps the dialog open", async () => {
  server.use(...llmEnabledHandlers());
  server.use(
    http.post("/api/analyses/:id/coach", () =>
      HttpResponse.json({ detail: "model 'bad-model' is not allowed on this server" }, { status: 422 }),
    ),
  );

  const user = userEvent.setup();
  renderPanel();

  await waitFor(() => expect(screen.getByRole("button", { name: "Re-run coaching" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Re-run coaching" }));
  await waitFor(() => expect(screen.getByLabelText("Model")).toHaveTextContent("qwen3:8b"));
  await user.click(screen.getByRole("button", { name: "Run" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "model 'bad-model' is not allowed on this server",
  );
  expect(screen.getByRole("heading", { name: "Re-run coaching" })).toBeInTheDocument();
});

test("the Model select shows 'No models available' and keeps Run disabled when the list is empty", async () => {
  server.use(
    http.get("/api/me", () =>
      HttpResponse.json({
        id: "00000000-0000-0000-0000-000000000001",
        email: "demo@example.com",
        username: "Demo User",
        drive_connected: false,
        llm_enabled: true,
        llm_provider: "openai_compatible",
      }),
    ),
    http.get("/api/llm/models", () =>
      HttpResponse.json({ enabled: true, provider: "openai_compatible", models: [] }),
    ),
  );

  const user = userEvent.setup();
  renderPanel();

  await waitFor(() => expect(screen.getByRole("button", { name: "Re-run coaching" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Re-run coaching" }));
  await user.click(screen.getByLabelText("Model"));

  expect(await screen.findByText("No models available")).toBeInTheDocument();

  // Closing the dropdown first: Radix marks the rest of the page aria-hidden while the
  // listbox is open, which would otherwise hide the dialog's own Run button from this query.
  await user.keyboard("{Escape}");
  expect(await screen.findByRole("button", { name: "Run" })).toBeDisabled();
});
