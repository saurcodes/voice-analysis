import type { components } from "@/api/types";

/**
 * Formatting, label maps and transcript-highlighting helpers for the Analysis page
 * (src/pages/AnalysisPage.tsx and src/components/analysis/*). Kept framework-free (no
 * React) so Task 6's Compare page can import METRIC_LABELS and fmt() without pulling in
 * any Analysis-page-only component code.
 */

type MetricsReport = components["schemas"]["MetricsReport"];
type Transcript = components["schemas"]["Transcript"];

/** value.toFixed(digits), except a value that rounds to zero never prints as "-0.0". */
function toFixedNoNegativeZero(value: number, digits: number): string {
  const s = value.toFixed(digits);
  return /^-0(\.0*)?$/.test(s) ? s.slice(1) : s;
}

/** "-" for null/undefined/NaN; otherwise value.toFixed(digits) ("-0.0" normalised to "0.0").
 * Zero em-dashes anywhere in this app: every "not available" render is the plain ASCII
 * hyphen. */
export function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return toFixedNoNegativeZero(value, digits);
}

/** Same as fmt(), but for a 0..1 fraction rendered as a percent (0.0625 -> "6.3"). */
export function fmtPercent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || Number.isNaN(fraction)) return "-";
  return fmt(fraction * 100, digits);
}

/** The first 8 characters of a config hash, without its "sha256:" algorithm prefix. */
export function shortHash(hash: string): string {
  return hash.replace(/^sha256:/, "").slice(0, 8);
}

const axisTickFormat = new Intl.NumberFormat("en", {
  maximumSignificantDigits: 3,
  notation: "compact",
});

/** Y-axis tick label: at most 3 significant digits ("0.0123", "1.23", "12.3K") so small
 * decimals fit the axis instead of clipping, and never "-0". */
export function formatAxisTick(value: number): string {
  if (!Number.isFinite(value)) return "";
  return value === 0 ? "0" : axisTickFormat.format(value);
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
  /**
   * "fraction" marks a raw 0..1 ratio that should be rendered as a percent (via
   * fmtPercent/formatMetricValue below) rather than as a bare number; absent means render
   * with fmt() as-is. Added for Task 6 (Compare page), which formats table and chart values
   * generically from this map instead of per-field fmt()/fmtPercent() calls.
   */
  kind?: "fraction";
  /** Decimal digits passed to fmt()/fmtPercent() when formatting generically; defaults to 1. */
  digits?: number;
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
  "pitch.creak_fraction_below_100hz": {
    label: "Creak below 100 Hz",
    unit: "%",
    meaning: "Share of voiced speech with creaky (vocal fry) pitch below 100 Hz.",
    kind: "fraction",
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
  "phrasing.long_pause_count_ge_1s": {
    label: "Long pauses",
    unit: "",
    meaning: "Pauses of a second or more.",
    digits: 0,
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
  "energy.final_vs_body_db": {
    label: "Final vs body loudness",
    unit: "dB",
    meaning: "How much quieter (or louder) the final stretch is than the rest of the recording.",
  },
  "articulation.hf_energy_ratio_db": {
    label: "High-frequency energy",
    unit: "dB",
    meaning: "Relative energy in the high-frequency band, a proxy for crisp articulation.",
  },
  "articulation.modulation_depth": {
    label: "Modulation depth",
    unit: "",
    meaning: "How strongly the syllable rhythm rises and falls.",
    digits: 2,
  },
  "articulation.vowel_space.vowel_space_area_hz2": {
    label: "Vowel space area",
    unit: "Hz²",
    meaning: "How distinct vowels sound from each other.",
    digits: 0,
  },
  "articulation.weak_peak_fraction": {
    label: "Weak syllable peaks",
    unit: "%",
    meaning: "Share of syllables with a weak, under-articulated peak.",
    kind: "fraction",
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
    kind: "fraction",
  },
  "transcript.derived.clarity.low_conf_word_fraction": {
    label: "Low-confidence words",
    unit: "%",
    meaning: "Share of words the transcriber was not confident about.",
    kind: "fraction",
  },
  "transcript.derived.clarity.rushed_word_fraction": {
    label: "Rushed words",
    unit: "%",
    meaning: "Share of words spoken in a rushed run.",
    kind: "fraction",
  },
};

/** "-" for null, "6.3" / "42" etc. otherwise; picks fmt() vs fmtPercent() and the digit count
 * from a METRIC_LABELS entry (Task 6's Compare page formats generically from the map instead
 * of per-field calls like SummaryCards does). Falls back to fmt() with 1 digit when the path
 * has no label entry, so an unrecognised path still renders a plain number instead of crashing. */
export function formatMetricValue(label: MetricLabel | undefined, value: number | null | undefined): string {
  const digits = label?.digits ?? 1;
  return label?.kind === "fraction" ? fmtPercent(value, digits) : fmt(value, digits);
}

/**
 * "+2.6" / "-1.5" / "0.0" for a comparison delta, applying the label's fraction->percent and
 * digit formatting. A delta that rounds to zero at the display precision prints "0.0" with no
 * sign (never "-0.0" or "+0.0"); `isZero` tells the caller to show the neutral arrow too.
 */
export function formatSignedDelta(
  label: MetricLabel | undefined,
  delta: number | null,
): { text: string; isZero: boolean } {
  if (delta === null || Number.isNaN(delta)) return { text: "-", isZero: false };
  const digits = label?.digits ?? 1;
  const magnitude = label?.kind === "fraction" ? Math.abs(delta) * 100 : Math.abs(delta);
  const text = toFixedNoNegativeZero(magnitude, digits);
  const isZero = Number(text) === 0;
  if (isZero) return { text, isZero };
  return { text: `${delta > 0 ? "+" : "-"}${text}`, isZero };
}

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
