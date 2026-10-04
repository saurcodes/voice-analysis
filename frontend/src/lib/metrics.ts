import type { components } from "@/api/types";

/**
 * Formatting, label maps and transcript-highlighting helpers for the Analysis page
 * (src/pages/AnalysisPage.tsx and src/components/analysis/*). Kept framework-free (no
 * React) so Task 6's Compare page can import METRIC_LABELS and fmt() without pulling in
 * any Analysis-page-only component code.
 */

type MetricsReport = components["schemas"]["MetricsReport"];
type Transcript = components["schemas"]["Transcript"];

/** "-" for null/undefined/NaN; otherwise value.toFixed(digits). Zero em-dashes anywhere
 * in this app: every "not available" render is the plain ASCII hyphen. */
export function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(digits);
}

/** Same as fmt(), but for a 0..1 fraction rendered as a percent (0.0625 -> "6.3"). */
export function fmtPercent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "-";
  return fmt(fraction * 100, digits);
}

/** "0:00" / "1:05" for a chart x-axis tick or table cell given a seconds offset. */
export function formatClockTime(totalSeconds: number): string {
  const safe = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export interface MetricLabel {
  /** Short card/row label, sentence case. */
  label: string;
  /** Unit suffix shown next to the value ("Hz", "st", "%", "/min", "syl/s", "count"). */
  unit: string;
  /** One-line plain-language meaning shown under the value. */
  meaning: string;
}

/**
 * Human labels for MetricsReport / Transcript fields, keyed by the same dotted path
 * convention the backend already uses for comparison.directions in PublicConfig (see
 * src/test/handlers.ts's publicConfig.comparison.directions) - e.g. "pitch.f0_range_st",
 * "transcript.derived.clarity.word_final_drop_fraction". Task 6 (Compare page) can reuse
 * these same keys for its comparison rows instead of re-deriving labels.
 */
export const METRIC_LABELS: Record<string, MetricLabel> = {
  "pitch.f0_median_hz": {
    label: "Median pitch",
    unit: "Hz",
    meaning: "Typical pitch across the recording.",
  },
  "pitch.f0_range_st": {
    label: "Pitch range",
    unit: "st",
    meaning: "How much pitch varies, in semitones.",
  },
  "intonation.flat_pct": {
    label: "Flat endings",
    unit: "%",
    meaning: "Share of phrases that end without a clear rise or fall.",
  },
  "phrasing.pauses_per_min": {
    label: "Pauses per minute",
    unit: "/min",
    meaning: "How often you pause while speaking.",
  },
  "pace.articulation_rate_syl_per_sec": {
    label: "Articulation rate",
    unit: "syl/s",
    meaning: "Speaking speed during active speech, excluding pauses.",
  },
  "energy.trailing_off_count": {
    label: "Trailing off",
    unit: "",
    meaning: "Phrases whose volume quietly fades near the end.",
  },
  "transcript.derived.fillers_per_min": {
    label: "Fillers per minute",
    unit: "/min",
    meaning: 'How often filler words like "um" or "so" appear.',
  },
  "transcript.derived.clarity.word_final_drop_fraction": {
    label: "Eaten words",
    unit: "%",
    meaning: "Share of words whose ending drops out and becomes hard to hear.",
  },
};

/** The 8 Summary cards, in display order, as paths into METRIC_LABELS. */
export const SUMMARY_CARD_PATHS = [
  "pitch.f0_median_hz",
  "pitch.f0_range_st",
  "intonation.flat_pct",
  "phrasing.pauses_per_min",
  "pace.articulation_rate_syl_per_sec",
  "energy.trailing_off_count",
  "transcript.derived.fillers_per_min",
  "transcript.derived.clarity.word_final_drop_fraction",
] as const;

/** Timeline has nothing worth charting: no windows, or every F0 sample is null (e.g. a
 * too_short / no_voiced_speech recording where only the scalar counts are 0/false). */
export function isTimelineEmpty(metrics: MetricsReport | null | undefined): boolean {
  const windows = metrics?.timeline.windows ?? [];
  if (windows.length === 0) return true;
  return windows.every((window) => window.f0_median_hz === null);
}

export type TranscriptFlag = "filler" | "eaten" | "lowconf";

export interface Token {
  kind: "word" | "pause";
  text: string;
  start_s: number;
  /** Word tokens only. */
  end_s?: number;
  flags: Set<TranscriptFlag>;
  /** Pause tokens only. */
  duration_s?: number;
}

/** Lowercase and strip surrounding punctuation so "So," / "SO" / "so" all compare equal,
 * and so they match the plain lowercase keys transcript.derived.filler_counts uses. */
function normaliseWord(raw: string): string {
  return raw.toLowerCase().replace(/[^a-z0-9']/g, "");
}

function matchesAnyTime(times: number[], target: number): boolean {
  return times.some((time) => Math.abs(time - target) <= 0.01);
}

/**
 * Flattens a Transcript's words into highlight Tokens: filler words/phrases (matched
 * case-insensitively against transcript.derived.filler_counts' keys, multi-word fillers
 * like "you know" marking every word in the phrase), eaten and low-confidence words
 * (matched against derived.clarity.eaten_words / low_conf_words by start_s, +/- 0.01s),
 * and pause tokens spliced in wherever a metrics.phrasing.long_pauses entry of >= 1s
 * falls between two words.
 */
export function highlightTranscript(
  transcript: Transcript | null | undefined,
  metrics: MetricsReport | null | undefined,
): Token[] {
  if (!transcript) return [];

  const words = transcript.words;
  const { filler_counts: fillerCounts, clarity } = transcript.derived;

  const activeFillers = Object.keys(fillerCounts).filter((key) => fillerCounts[key] > 0);
  const multiWordFillers = activeFillers
    .filter((key) => key.includes(" "))
    .map((key) => key.split(" ").map(normaliseWord));
  const singleWordFillers = new Set(
    activeFillers.filter((key) => !key.includes(" ")).map(normaliseWord),
  );

  const fillerIndexes = new Set<number>();
  words.forEach((word, i) => {
    if (singleWordFillers.has(normaliseWord(word.word))) fillerIndexes.add(i);
  });
  for (const parts of multiWordFillers) {
    for (let i = 0; i <= words.length - parts.length; i++) {
      const isMatch = parts.every((part, j) => normaliseWord(words[i + j].word) === part);
      if (isMatch) {
        for (let j = 0; j < parts.length; j++) fillerIndexes.add(i + j);
      }
    }
  }

  const eatenTimes = clarity.eaten_words.map((word) => word.start_s);
  const lowConfTimes = clarity.low_conf_words.map((word) => word.start_s);

  const longPauses = (metrics?.phrasing.long_pauses ?? [])
    .filter((pause) => pause.duration_s >= 1)
    .slice()
    .sort((a, b) => a.start_s - b.start_s);

  function pauseToken(pause: { start_s: number; duration_s: number }): Token {
    return {
      kind: "pause",
      text: `pause ${pause.duration_s.toFixed(1)}s`,
      start_s: pause.start_s,
      duration_s: pause.duration_s,
      flags: new Set<TranscriptFlag>(),
    };
  }

  const tokens: Token[] = [];
  let pauseCursor = 0;

  words.forEach((word, i) => {
    while (pauseCursor < longPauses.length && longPauses[pauseCursor].start_s < word.start_s) {
      tokens.push(pauseToken(longPauses[pauseCursor]));
      pauseCursor += 1;
    }

    const flags = new Set<TranscriptFlag>();
    if (fillerIndexes.has(i)) flags.add("filler");
    if (matchesAnyTime(eatenTimes, word.start_s)) flags.add("eaten");
    if (matchesAnyTime(lowConfTimes, word.start_s)) flags.add("lowconf");

    tokens.push({
      kind: "word",
      text: word.word,
      start_s: word.start_s,
      end_s: word.end_s,
      flags,
    });
  });

  while (pauseCursor < longPauses.length) {
    tokens.push(pauseToken(longPauses[pauseCursor]));
    pauseCursor += 1;
  }

  return tokens;
}
