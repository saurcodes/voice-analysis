import { http, HttpResponse } from "msw";
import type { components } from "@/api/types";
import { analysisDetail, coaching, comparison, jobStatus, summary } from "./fixtures";

/**
 * MSW handlers for every endpoint the app calls. Covers auth bootstrap, config and LLM
 * availability (unconditional, feature-independent), plus analyses/jobs/comparisons/upload
 * for the hooks in src/api/hooks.ts, src/api/upload.ts and src/api/sse.ts. Individual tests
 * override any of these with server.use(...) for error paths, empty states, etc.
 */

const publicConfig: components["schemas"]["PublicConfig"] = {
  analysis: {
    pitch_floor_hz: 75,
    pitch_ceiling_hz: 350,
    time_step_s: 0.01,
    silence_threshold_db: -25,
    min_pause_s: 0.25,
    min_sounding_s: 0.1,
    creak_threshold_hz: 100,
    opening_window_s: 5,
    syllable_peak_prominence_db: 2,
    intonation_tail_s: 0.08,
    intonation_threshold_st: 1.5,
    energy_window_s: 15,
    phrase_end_tail_s: 0.3,
    trailing_off_drop_db: 6,
    noise_floor_percentile: 5,
    low_confidence_noise_floor_db: 45,
    low_confidence_snr_db: 15,
    low_confidence_f0_hz: 250,
    min_duration_s: 2.0,
  },
  articulation: {
    hf_band_hz: [2000, 8000],
    lf_band_hz: [0, 1000],
    modulation_band_hz: [2, 10],
    weak_peak_prominence_db: 4,
    formant_max_hz: 5500,
    formant_trim_pct: 5,
  },
  clarity: {
    low_conf_word_prob: 0.5,
    word_final_drop_db: 6,
    word_final_tail_fraction: 0.3,
    min_word_duration_s: 0.25,
    rushed_syl_per_sec: 7,
    rushed_run_min_words: 3,
    low_logprob_segment: -1.0,
  },
  comparison: {
    min_meaningful_change_pct: 5,
    directions: {
      "pitch.f0_range_st": "up_good",
      "pitch.creak_fraction_below_100hz": "down_good",
      "phrasing.long_pause_count_ge_1s": "down_good",
      "phrasing.pauses_per_min": "neutral",
      "intonation.flat_pct": "down_good",
      "energy.trailing_off_count": "down_good",
      "energy.final_vs_body_db": "up_good",
      "articulation.hf_energy_ratio_db": "up_good",
      "articulation.modulation_depth": "up_good",
      "articulation.vowel_space.vowel_space_area_hz2": "up_good",
      "articulation.weak_peak_fraction": "down_good",
      "transcript.derived.fillers_per_min": "down_good",
      "transcript.derived.clarity.low_conf_word_fraction": "down_good",
      "transcript.derived.clarity.word_final_drop_fraction": "down_good",
      "transcript.derived.clarity.rushed_word_fraction": "down_good",
    },
  },
};

const meResponse: components["schemas"]["MeResponse"] = {
  id: "00000000-0000-0000-0000-000000000001",
  email: "demo@example.com",
  username: "Demo User",
  drive_connected: false,
  llm_enabled: false,
  llm_provider: null,
};

const llmModels: components["schemas"]["LlmModels"] = {
  enabled: false,
  provider: null,
  models: [],
};

const summaryList: components["schemas"]["AnalysisSummary"][] = [
  summary(),
  summary({
    id: "a1a1a1a1-0000-4000-8000-000000000002",
    file_name: "follow-up.wav",
    recorded_at: "2026-09-30T09:15:00Z",
    analysed_at: "2026-09-30T09:15:35Z",
  }),
  summary({
    id: "a1a1a1a1-0000-4000-8000-000000000003",
    file_name: "too-quiet.wav",
    recorded_at: "2026-10-01T11:00:00Z",
    analysed_at: "2026-10-01T11:00:05Z",
    has_transcript: false,
    f0_median_hz: null,
    f0_range_st: null,
    flat_pct: null,
    pauses_per_min: null,
    articulation_rate_syl_per_sec: null,
    trailing_off_count: null,
    fillers_per_min: null,
  }),
];

const jobList: components["schemas"]["JobStatus"][] = [
  jobStatus({ id: "b2b2b2b2-0000-4000-8000-000000000001", status: "running", stage: "analyse", progress_pct: 60 }),
  jobStatus({
    id: "b2b2b2b2-0000-4000-8000-000000000002",
    status: "done",
    stage: "done",
    progress_pct: 100,
    analysis_id: "a1a1a1a1-0000-4000-8000-000000000001",
  }),
  jobStatus({
    id: "b2b2b2b2-0000-4000-8000-000000000003",
    status: "failed",
    stage: "transcribe",
    progress_pct: 70,
    error: "transcription backend unavailable",
  }),
];

export const handlers = [
  http.get("/api/me", () => HttpResponse.json(meResponse)),
  http.get("/api/config/public", () => HttpResponse.json(publicConfig)),
  http.get("/api/llm/models", () => HttpResponse.json(llmModels)),

  http.get("/api/analyses", ({ request }) => {
    const url = new URL(request.url);
    const limit = Number(url.searchParams.get("limit") ?? "50");
    const offset = Number(url.searchParams.get("offset") ?? "0");
    return HttpResponse.json(summaryList.slice(offset, offset + limit));
  }),

  http.post("/api/analyses", async ({ request }) => {
    const form = await request.formData();
    if (!(form.get("file") instanceof File)) {
      return HttpResponse.json({ detail: "file is required" }, { status: 422 });
    }
    return HttpResponse.json({ job_ids: [jobStatus().id] }, { status: 202 });
  }),

  http.get("/api/analyses/:id", ({ params }) =>
    HttpResponse.json(analysisDetail("default", { id: params.id as string })),
  ),

  http.delete("/api/analyses/:id", () => new HttpResponse(null, { status: 204 })),

  http.get("/api/analyses/:id/raw/:kind", ({ params }) => {
    const detail = analysisDetail("default", { id: params.id as string });
    if (params.kind === "transcript") return HttpResponse.json(detail.transcript);
    return HttpResponse.json(detail.metrics);
  }),

  http.get("/api/jobs", ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    const jobs = status ? jobList.filter((job) => job.status === status) : jobList;
    return HttpResponse.json(jobs);
  }),

  http.get("/api/jobs/:id", ({ params }) => {
    const job = jobList.find((j) => j.id === params.id) ?? jobStatus({ id: params.id as string });
    return HttpResponse.json(job);
  }),

  http.post("/api/jobs/:id/retry", ({ params }) =>
    HttpResponse.json({ job_id: params.id as string }, { status: 202 }),
  ),

  http.get("/api/jobs/:id/events", () => {
    // CRLF line/frame terminators, matching the real backend's sse-starlette 3.x output
    // (its default separator is "\r\n", not the bare "\n" the SSE spec's examples use).
    const body =
      'event: stage\r\ndata: {"stage":"analyse","progress_pct":50}\r\n\r\n' +
      `event: done\r\ndata: {"analysis_id":"${analysisDetail().id}"}\r\n\r\n`;
    return new HttpResponse(body, { headers: { "content-type": "text/event-stream" } });
  }),

  http.get("/api/comparisons", () => HttpResponse.json(comparison())),

  http.post("/api/analyses/:id/coach", ({ params }) =>
    HttpResponse.json(
      analysisDetail("default", {
        id: params.id as string,
        coaching: coaching(),
        coaching_warnings: ["number 17.5 in what_is_lacking does not match any metric value"],
      }),
    ),
  ),
];

/**
 * Override handlers for a server with coaching turned on: /api/me reports llm_enabled, and
 * /api/llm/models lists a couple of models. Individual tests bring these in with
 * `server.use(...llmEnabledHandlers())` rather than baking them into the default handlers
 * above, since most tests exercise the (much more common) coaching-disabled default.
 */
export function llmEnabledHandlers(models: string[] = ["qwen3:8b", "llama3.2:latest"]) {
  return [
    http.get("/api/me", () =>
      HttpResponse.json({ ...meResponse, llm_enabled: true, llm_provider: "openai_compatible" }),
    ),
    http.get("/api/llm/models", () =>
      HttpResponse.json({ enabled: true, provider: "openai_compatible", models }),
    ),
  ];
}
