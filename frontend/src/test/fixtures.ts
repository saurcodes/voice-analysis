import type { components } from "@/api/types";

/**
 * Typed fixture builders for the shapes real API responses take (copied from
 * .superpowers/sdd/2026-10-04-plan-5-react-ui/samples/detail.json and detail2.json: real
 * smoke-test output, not hand-wavy placeholders). Every builder takes an optional partial
 * override so a test can nudge one field without re-stating the whole shape.
 */

type AnalysisSummary = components["schemas"]["AnalysisSummary"];
type AnalysisDetail = components["schemas"]["AnalysisDetail"];
type JobStatus = components["schemas"]["JobStatus"];
type ComparisonResult = components["schemas"]["ComparisonResult"];
type MetricsReport = components["schemas"]["MetricsReport"];
type Transcript = components["schemas"]["Transcript"];
type TranscriptWord = components["schemas"]["TranscriptWord"];
type TranscriptSegment = components["schemas"]["TranscriptSegment"];

export function summary(overrides: Partial<AnalysisSummary> = {}): AnalysisSummary {
  return {
    id: "a1a1a1a1-0000-4000-8000-000000000001",
    file_name: "practice-run.wav",
    drive_file_id: null,
    recorded_at: "2026-09-28T14:03:00Z",
    analysed_at: "2026-09-28T14:03:40Z",
    analyser_version: "0.1.0",
    config_hash: "sha256:b60fb6886079e114c489b8e7783a089553f2fd7817d0ca72c7fc21fb96ab516",
    has_transcript: true,
    has_coaching: false,
    f0_median_hz: 165.4,
    f0_range_st: 10.8,
    flat_pct: 20.0,
    pauses_per_min: 12.0,
    articulation_rate_syl_per_sec: 3.1,
    trailing_off_count: 1,
    fillers_per_min: 18.0,
    ...overrides,
  };
}

export function jobStatus(overrides: Partial<JobStatus> = {}): JobStatus {
  return {
    id: "b2b2b2b2-0000-4000-8000-000000000001",
    status: "running",
    stage: "analyse",
    progress_pct: 40,
    error: null,
    analysis_id: null,
    file_name: "practice-run.wav",
    created_at: "2026-09-28T14:03:00Z",
    ...overrides,
  };
}

// --- analysisDetail: word-level transcript, built once so derived stats below (word_count,
// filler_counts, low_conf_words, ...) stay consistent with the words actually listed. ---

const WORD_TEXTS = [
  "So", "um", "I", "wanted", "to", "walk", "you", "through", "the", "quarterly",
  "results", "today", "and", "you", "know", "we", "should", "focus", "on", "what",
  "matters", "most", "um", "so", "actually", "we", "delivered", "strong", "growth", "across",
  "every", "region",
] as const;

// probability < clarity.low_conf_word_prob (0.5 in the public config fixture): both "um"s
// and one otherwise-ordinary word ("growth"), so there's at least one genuinely
// low-confidence word alongside the two filler "um"s.
const LOW_PROB_INDEXES: Record<number, number> = { 1: 0.42, 22: 0.38, 28: 0.41 };

const WORD_STEP_S = 0.55;
const WORD_DUR_S = 0.35;
const WORD_START_OFFSET_S = 0.2;

function buildWords(): TranscriptWord[] {
  return WORD_TEXTS.map((word, i) => {
    const start_s = Number((WORD_START_OFFSET_S + i * WORD_STEP_S).toFixed(2));
    return {
      word,
      start_s,
      end_s: Number((start_s + WORD_DUR_S).toFixed(2)),
      probability: LOW_PROB_INDEXES[i] ?? 0.95,
    };
  });
}

function buildSegments(words: TranscriptWord[]): TranscriptSegment[] {
  const groups: Array<{ range: [number, number]; avg_logprob: number; no_speech_prob: number }> = [
    { range: [0, 12], avg_logprob: -0.25, no_speech_prob: 0.015 },
    { range: [12, 22], avg_logprob: -0.38, no_speech_prob: 0.02 },
    { range: [22, 25], avg_logprob: -0.52, no_speech_prob: 0.05 },
    { range: [25, 29], avg_logprob: -0.19, no_speech_prob: 0.01 },
    { range: [29, 32], avg_logprob: -0.17, no_speech_prob: 0.01 },
  ];
  return groups.map(({ range: [start, end], avg_logprob, no_speech_prob }) => {
    const slice = words.slice(start, end);
    return {
      start_s: slice[0].start_s,
      end_s: slice[slice.length - 1].end_s,
      text: slice.map((w) => w.word).join(" "),
      avg_logprob,
      no_speech_prob,
    };
  });
}

function buildTranscript(): Transcript {
  const words = buildWords();
  const segments = buildSegments(words);
  const lowConfWords = [1, 22, 28].map((i) => ({
    word: words[i].word,
    start_s: words[i].start_s,
    end_s: words[i].end_s,
    probability: words[i].probability,
  }));
  const eatenWord = words[20];

  return {
    schema_version: "1.0",
    model: "small",
    language: "en",
    text: segments.map((s) => s.text).join(" "),
    segments,
    words,
    derived: {
      word_count: words.length,
      words_per_min: 96.0,
      filler_counts: { so: 2, uh: 0, um: 2, like: 0, actually: 1, "you know": 1, basically: 0 },
      filler_total: 6,
      fillers_per_min: 18.0,
      clarity: {
        low_conf_word_fraction: 0.094,
        low_conf_words: lowConfWords,
        word_final_drop_count: 2,
        word_final_drop_fraction: 0.0625,
        eaten_words: [
          { word: eatenWord.word, start_s: eatenWord.start_s, end_s: eatenWord.end_s, drop_db: 8.4 },
        ],
        rushed_word_fraction: 0.09375,
        rushed_runs: [{ start_s: words[25].start_s, end_s: words[27].end_s, text: "we delivered strong" }],
        segment_avg_logprob_mean: -0.3,
        low_logprob_segment_fraction: 0.0,
      },
    },
  };
}

function buildMetrics(): MetricsReport {
  return {
    schema_version: "1.0",
    analyser_version: "0.1.0",
    config_hash: "sha256:b60fb6886079e114c489b8e7783a089553f2fd7817d0ca72c7fc21fb96ab516",
    source: {
      file_name: "practice-run.wav",
      drive_file_id: null,
      drive_modified_time: null,
      content_sha256: "sha256-fixture-0001",
      duration_s: 20.0,
      original_channels: 1,
      original_sample_rate: 16000,
    },
    recording_quality: {
      noise_floor_db: -42.5,
      snr_estimate_db: 27.8,
      low_confidence: false,
      reasons: [],
    },
    pitch: {
      f0_median_hz: 165.4,
      f0_p10_hz: 118.2,
      f0_p90_hz: 240.6,
      f0_range_st: 10.8,
      voiced_fraction: 0.72,
      creak_fraction_below_100hz: 0.015,
      opening_f0_median_hz: 172.3,
      opening_vs_overall_st: 0.7,
    },
    phrasing: {
      phrase_count: 5,
      speaking_time_s: 14.2,
      mean_phrase_length_s: 2.84,
      pause_count: 4,
      pauses_per_min: 12.0,
      mean_pause_length_s: 0.6,
      long_pause_count_ge_1s: 1,
      long_pauses: [{ start_s: 9.0, end_s: 10.3, duration_s: 1.3 }],
    },
    pace: {
      syllable_count_est: 44,
      syllables_per_sec_overall: 2.2,
      articulation_rate_syl_per_sec: 3.1,
    },
    intonation: {
      up_count: 2,
      down_count: 2,
      flat_count: 1,
      unclassified_count: 0,
      flat_pct: 20.0,
      per_phrase: [
        { start_s: 0.2, end_s: 3.45, end_delta_st: 2.1, class: "up" },
        { start_s: 3.5, end_s: 7.95, end_delta_st: -1.8, class: "down" },
        { start_s: 8.0, end_s: 12.9, end_delta_st: 0.2, class: "flat" },
        { start_s: 12.95, end_s: 15.7, end_delta_st: 2.6, class: "up" },
        { start_s: 15.75, end_s: 17.6, end_delta_st: -2.4, class: "down" },
      ],
    },
    energy: {
      body_median_db: -24.6,
      final_15s_median_db: -27.1,
      final_vs_body_db: -2.5,
      trailing_off_count: 1,
      per_phrase_end_drop_db: [1.2, 0.8, 4.6, 0.9, 2.1],
    },
    voice_quality: {
      hnr_db: 14.2,
      jitter_local: 0.012,
      shimmer_local: 0.045,
      low_confidence: false,
    },
    articulation: {
      hf_energy_ratio_db: -9.8,
      spectral_tilt_db_per_oct: -5.2,
      modulation_depth: 0.42,
      syllable_peak_prominence_mean_db: 6.1,
      syllable_peak_prominence_p25_db: 3.4,
      weak_peak_fraction: 0.08,
      vowel_space: {
        f1_sd_hz: 120.5,
        f2_sd_hz: 310.2,
        vowel_space_area_hz2: 185000,
        vowel_dispersion_st: 4.2,
      },
      low_confidence: false,
    },
    timeline: {
      window_s: 2.5,
      windows: [
        { start_s: 0.0, end_s: 2.5, f0_median_hz: 160.2, f0_sd_st: 1.4, intensity_median_db: -26.5 },
        { start_s: 2.5, end_s: 5.0, f0_median_hz: 168.5, f0_sd_st: 1.8, intensity_median_db: -24.2 },
        { start_s: 5.0, end_s: 7.5, f0_median_hz: 172.1, f0_sd_st: 2.1, intensity_median_db: -23.8 },
        { start_s: 7.5, end_s: 10.0, f0_median_hz: 158.9, f0_sd_st: 1.6, intensity_median_db: -27.4 },
        { start_s: 10.0, end_s: 12.5, f0_median_hz: 180.3, f0_sd_st: 2.6, intensity_median_db: -22.1 },
        { start_s: 12.5, end_s: 15.0, f0_median_hz: 175.6, f0_sd_st: 2.0, intensity_median_db: -23.5 },
        { start_s: 15.0, end_s: 17.5, f0_median_hz: 162.7, f0_sd_st: 1.5, intensity_median_db: -25.9 },
        { start_s: 17.5, end_s: 20.0, f0_median_hz: 150.1, f0_sd_st: 1.1, intensity_median_db: -29.0 },
      ],
    },
  };
}

/**
 * A recording_quality failure variant: too short or no detected voiced speech, where the
 * analyser can't compute anything meaningful. Every block is still present (the schema
 * requires it), but every number inside it is null except the handful of non-nullable
 * scalar fields (counts, booleans), which fall back to 0/false/empty-array; transcript is
 * null outright.
 */
function buildEmptyMetrics(reason: "too_short" | "no_voiced_speech"): MetricsReport {
  const isTooShort = reason === "too_short";
  return {
    schema_version: "1.0",
    analyser_version: "0.1.0",
    config_hash: "sha256:b60fb6886079e114c489b8e7783a089553f2fd7817d0ca72c7fc21fb96ab516",
    source: {
      file_name: isTooShort ? "quick-check.wav" : "silent-room.wav",
      drive_file_id: null,
      drive_modified_time: null,
      content_sha256: isTooShort ? "sha256-fixture-0002" : "sha256-fixture-0003",
      duration_s: isTooShort ? 1.1 : 30.0,
      original_channels: 1,
      original_sample_rate: 16000,
    },
    recording_quality: {
      noise_floor_db: isTooShort ? null : -35.2,
      snr_estimate_db: null,
      low_confidence: true,
      reasons: [reason],
    },
    pitch: {
      f0_median_hz: null,
      f0_p10_hz: null,
      f0_p90_hz: null,
      f0_range_st: null,
      voiced_fraction: 0.0,
      creak_fraction_below_100hz: null,
      opening_f0_median_hz: null,
      opening_vs_overall_st: null,
    },
    phrasing: {
      phrase_count: 0,
      speaking_time_s: 0.0,
      mean_phrase_length_s: null,
      pause_count: 0,
      pauses_per_min: 0.0,
      mean_pause_length_s: null,
      long_pause_count_ge_1s: 0,
      long_pauses: [],
    },
    pace: {
      syllable_count_est: 0,
      syllables_per_sec_overall: 0.0,
      articulation_rate_syl_per_sec: null,
    },
    intonation: {
      up_count: 0,
      down_count: 0,
      flat_count: 0,
      unclassified_count: 0,
      flat_pct: null,
      per_phrase: [],
    },
    energy: {
      body_median_db: null,
      final_15s_median_db: null,
      final_vs_body_db: null,
      trailing_off_count: 0,
      per_phrase_end_drop_db: [],
    },
    voice_quality: {
      hnr_db: null,
      jitter_local: null,
      shimmer_local: null,
      low_confidence: true,
    },
    articulation: {
      hf_energy_ratio_db: null,
      spectral_tilt_db_per_oct: null,
      modulation_depth: null,
      syllable_peak_prominence_mean_db: null,
      syllable_peak_prominence_p25_db: null,
      weak_peak_fraction: null,
      vowel_space: {
        f1_sd_hz: null,
        f2_sd_hz: null,
        vowel_space_area_hz2: null,
        vowel_dispersion_st: null,
      },
      low_confidence: true,
    },
    timeline: {
      window_s: 15.0,
      windows: [],
    },
  };
}

export type AnalysisDetailVariant = "default" | "too_short" | "no_voiced_speech";

export function analysisDetail(
  variant: AnalysisDetailVariant = "default",
  overrides: Partial<AnalysisDetail> = {},
): AnalysisDetail {
  const base: AnalysisDetail =
    variant === "default"
      ? {
          id: "c3c3c3c3-0000-4000-8000-000000000001",
          file_name: "practice-run.wav",
          drive_file_id: null,
          recorded_at: "2026-09-28T14:03:00Z",
          analysed_at: "2026-09-28T14:03:40Z",
          analyser_version: "0.1.0",
          config_hash: "sha256:b60fb6886079e114c489b8e7783a089553f2fd7817d0ca72c7fc21fb96ab516",
          metrics: buildMetrics(),
          transcript: buildTranscript(),
          speaker_context: null,
          coaching: null,
          coaching_warnings: null,
        }
      : {
          id:
            variant === "too_short"
              ? "c3c3c3c3-0000-4000-8000-000000000002"
              : "c3c3c3c3-0000-4000-8000-000000000003",
          file_name: variant === "too_short" ? "quick-check.wav" : "silent-room.wav",
          drive_file_id: null,
          recorded_at: "2026-09-28T14:03:00Z",
          analysed_at: "2026-09-28T14:03:02Z",
          analyser_version: "0.1.0",
          config_hash: "sha256:b60fb6886079e114c489b8e7783a089553f2fd7817d0ca72c7fc21fb96ab516",
          metrics: buildEmptyMetrics(variant),
          transcript: null,
          speaker_context: null,
          coaching: null,
          coaching_warnings: null,
        };

  return { ...base, ...overrides };
}

/**
 * Coaching fixture: realistic two-item lists plus a marked_up_example that quotes the
 * default transcript fixture's words (see WORD_TEXTS/buildTranscript above), decorated with
 * the "//" pause marker, a CAPS emphasis word and a "down" intonation arrow, matching what
 * the real LLM output looks like. "17.5" in what_is_lacking is the number the default coach
 * handler's coaching_warnings flags as an unmatched token (see handlers.ts).
 */
export function coaching(overrides: Partial<Record<string, unknown>> = {}): Record<string, unknown> {
  return {
    what_improved: [
      "Pitch range widened to 10.8 semitones, more expressive than the opening.",
      "Trailing-off dropped to just 1 instance across the whole recording.",
    ],
    what_is_lacking: [
      "Filler words still run high at 18.0 per minute, mostly um and you know.",
      "Energy fades over the final 17.5 seconds before the close.",
    ],
    next_steps: [
      "Cut the scripted filler phrase \"you know\" from the opening.",
      "Hold the final sentence's energy instead of trailing off at the end.",
    ],
    marked_up_example:
      "So um I wanted to walk you through the quarterly RESULTS today// and you " +
      "know we should focus on what matters most↘ um so actually we delivered strong growth",
    ...overrides,
  };
}

export function comparison(): ComparisonResult {
  const ids = ["a1a1a1a1-0000-4000-8000-000000000001", "a1a1a1a1-0000-4000-8000-000000000002"];
  const recordedAt = ["2026-09-20T10:00:00Z", "2026-09-28T14:03:00Z"];

  return {
    analysis_ids: ids,
    recorded_at: recordedAt,
    config_mismatch: false,
    analyser_version_mismatch: true,
    rows: [
      {
        path: "pitch.f0_range_st",
        direction: "up_good",
        values: [8.2, 10.8],
        step_deltas: [2.6],
        delta: 2.6,
        arrow: "up",
        verdict: "improved",
        partial: false,
      },
      {
        path: "pitch.creak_fraction_below_100hz",
        direction: "down_good",
        values: [0.03, 0.015],
        step_deltas: [-0.015],
        delta: -0.015,
        arrow: "down",
        verdict: "improved",
        partial: false,
      },
      {
        path: "phrasing.long_pause_count_ge_1s",
        direction: "down_good",
        values: [3, 1],
        step_deltas: [-2],
        delta: -2,
        arrow: "down",
        verdict: "improved",
        partial: false,
      },
      {
        path: "transcript.derived.fillers_per_min",
        direction: "down_good",
        values: [24.0, 18.0],
        step_deltas: [-6.0],
        delta: -6.0,
        arrow: "down",
        verdict: "improved",
        partial: false,
      },
      {
        path: "articulation.weak_peak_fraction",
        direction: "down_good",
        values: [null, 0.08],
        step_deltas: [null],
        delta: null,
        arrow: "flat",
        verdict: "unavailable",
        partial: true,
      },
    ],
    trend: {
      "pitch.f0_range_st": [
        { analysis_id: ids[0], recorded_at: recordedAt[0], value: 8.2 },
        { analysis_id: ids[1], recorded_at: recordedAt[1], value: 10.8 },
      ],
    },
  };
}
