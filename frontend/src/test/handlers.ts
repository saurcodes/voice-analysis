import { http, HttpResponse } from "msw";
import type { components } from "@/api/types";

/**
 * Base MSW handlers for the endpoints every page touches regardless of feature
 * (auth bootstrap, config, LLM availability). Task 3 adds analyses/jobs/comparisons
 * handlers alongside the pages that need them.
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

export const handlers = [
  http.get("/api/me", () => HttpResponse.json(meResponse)),
  http.get("/api/config/public", () => HttpResponse.json(publicConfig)),
  http.get("/api/llm/models", () => HttpResponse.json(llmModels)),
];
