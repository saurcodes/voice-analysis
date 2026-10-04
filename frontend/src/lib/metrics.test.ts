import { describe, expect, it } from "vitest";
import type { components } from "@/api/types";
import {
  fmt,
  fmtPercent,
  formatAxisTick,
  formatClockTime,
  formatSignedDelta,
  highlightTranscript,
  isTimelineEmpty,
  shortHash,
} from "./metrics";

type Transcript = components["schemas"]["Transcript"];
type MetricsReport = components["schemas"]["MetricsReport"];

describe("fmt", () => {
  it("renders null as a plain hyphen", () => {
    expect(fmt(null)).toBe("-");
  });

  it("renders undefined and NaN as a plain hyphen too", () => {
    expect(fmt(undefined)).toBe("-");
    expect(fmt(Number.NaN)).toBe("-");
  });

  it("rounds to 1 digit by default", () => {
    expect(fmt(12.345)).toBe("12.3");
  });

  it("honours an explicit digits argument", () => {
    expect(fmt(12.345, 2)).toBe("12.35");
    expect(fmt(12, 0)).toBe("12");
  });
});

describe("fmtPercent", () => {
  it("renders null as a plain hyphen", () => {
    expect(fmtPercent(null)).toBe("-");
  });

  it("scales a 0..1 fraction to a percent string", () => {
    expect(fmtPercent(0.0625)).toBe("6.3");
  });

  it("never prints a negative zero", () => {
    expect(fmtPercent(-0.0001)).toBe("0.0");
  });
});

describe("negative zero", () => {
  it("fmt normalises values that round to -0", () => {
    expect(fmt(-0.04)).toBe("0.0");
    expect(fmt(-0)).toBe("0.0");
    expect(fmt(-0.4, 0)).toBe("0");
    expect(fmt(-0.05)).toBe("-0.1");
  });

  it("formatSignedDelta prints an unsigned 0.0 and flags it as zero", () => {
    expect(formatSignedDelta(undefined, -0.04)).toEqual({ text: "0.0", isZero: true });
    expect(formatSignedDelta(undefined, 0.04)).toEqual({ text: "0.0", isZero: true });
    expect(formatSignedDelta(undefined, 2.6)).toEqual({ text: "+2.6", isZero: false });
    expect(formatSignedDelta(undefined, -1.5)).toEqual({ text: "-1.5", isZero: false });
    expect(formatSignedDelta(undefined, null)).toEqual({ text: "-", isZero: false });
  });

  it("formatSignedDelta scales fraction labels to percent before rounding", () => {
    const label = { label: "Flat endings", unit: "%", meaning: "", kind: "fraction" as const, digits: 1 };
    expect(formatSignedDelta(label, -0.0004)).toEqual({ text: "0.0", isZero: true });
    expect(formatSignedDelta(label, 0.052)).toEqual({ text: "+5.2", isZero: false });
  });
});

describe("shortHash", () => {
  it("drops the sha256: prefix before taking 8 characters", () => {
    expect(shortHash("sha256:b60fb6886079e114c489")).toBe("b60fb688");
    expect(shortHash("abcdef0123456789")).toBe("abcdef01");
  });
});

describe("formatAxisTick", () => {
  it("keeps tick labels to 3 significant digits", () => {
    expect(formatAxisTick(0.0123456)).toBe("0.0123");
    expect(formatAxisTick(12.3456)).toBe("12.3");
    expect(formatAxisTick(1234)).toBe("1.23K");
    expect(formatAxisTick(-0)).toBe("0");
  });
});

describe("formatClockTime", () => {
  it("formats sub-minute offsets", () => {
    expect(formatClockTime(0)).toBe("0:00");
    expect(formatClockTime(5)).toBe("0:05");
  });

  it("formats minute-plus offsets", () => {
    expect(formatClockTime(65)).toBe("1:05");
  });
});

describe("isTimelineEmpty", () => {
  it("is true when there are no windows", () => {
    expect(isTimelineEmpty({ timeline: { window_s: 15, windows: [] } } as MetricsReport)).toBe(true);
  });

  it("is true when every window's F0 is null", () => {
    const metrics = {
      timeline: {
        window_s: 15,
        windows: [
          { start_s: 0, end_s: 15, f0_median_hz: null, f0_sd_st: null, intensity_median_db: -30 },
        ],
      },
    } as MetricsReport;
    expect(isTimelineEmpty(metrics)).toBe(true);
  });

  it("is false when at least one window has an F0 value", () => {
    const metrics = {
      timeline: {
        window_s: 15,
        windows: [
          { start_s: 0, end_s: 15, f0_median_hz: 160, f0_sd_st: 1.2, intensity_median_db: -24 },
        ],
      },
    } as MetricsReport;
    expect(isTimelineEmpty(metrics)).toBe(false);
  });
});

/** Minimal, hand-timed transcript + metrics pair built for these tests specifically (rather
 * than reusing src/test/fixtures.ts's analysisDetail(), whose synthetic long_pauses entry
 * overlaps a word's own span) so the pause-insertion point is unambiguous: word 2 ("there")
 * cleanly ends at 1.0s and word 3 ("world") cleanly starts at 2.6s, bracketing a 1.3s pause. */
function buildTranscript(overrides: Partial<Transcript["derived"]["clarity"]> = {}): Transcript {
  const words: Transcript["words"] = [
    { word: "So", start_s: 0.0, end_s: 0.3, probability: 0.95 },
    { word: "hi", start_s: 0.3, end_s: 0.6, probability: 0.95 },
    { word: "there", start_s: 0.6, end_s: 1.0, probability: 0.95 },
    { word: "world", start_s: 2.6, end_s: 3.0, probability: 0.3 },
    { word: "you", start_s: 3.0, end_s: 3.3, probability: 0.95 },
    { word: "know", start_s: 3.3, end_s: 3.6, probability: 0.95 },
    { word: "we", start_s: 3.6, end_s: 3.9, probability: 0.95 },
    { word: "shipped", start_s: 3.9, end_s: 4.3, probability: 0.95 },
  ];

  return {
    schema_version: "1.0",
    model: "small",
    language: "en",
    text: words.map((w) => w.word).join(" "),
    segments: [],
    words,
    derived: {
      word_count: words.length,
      words_per_min: 90,
      filler_counts: { so: 1, "you know": 1 },
      filler_total: 2,
      fillers_per_min: 20,
      clarity: {
        low_conf_word_fraction: 0.125,
        low_conf_words: [{ word: "world", start_s: 2.6, end_s: 3.0, probability: 0.3 }],
        word_final_drop_count: 1,
        word_final_drop_fraction: 0.125,
        eaten_words: [{ word: "shipped", start_s: 3.9, end_s: 4.3, drop_db: 7.2 }],
        rushed_word_fraction: 0,
        rushed_runs: [],
        segment_avg_logprob_mean: -0.2,
        low_logprob_segment_fraction: 0,
        ...overrides,
      },
    },
  };
}

function buildMetricsWithPause(): MetricsReport {
  return {
    phrasing: {
      long_pauses: [{ start_s: 1.0, end_s: 2.3, duration_s: 1.3 }],
    },
  } as unknown as MetricsReport;
}

describe("highlightTranscript", () => {
  it("returns no tokens for a null transcript", () => {
    expect(highlightTranscript(null, null)).toEqual([]);
  });

  it("inserts a pause token between the last word before it and the first word after it", () => {
    const tokens = highlightTranscript(buildTranscript(), buildMetricsWithPause());
    const pauseIndex = tokens.findIndex((t) => t.kind === "pause");
    expect(pauseIndex).toBeGreaterThan(-1);
    expect(tokens[pauseIndex - 1]).toMatchObject({ kind: "word", text: "there" });
    expect(tokens[pauseIndex + 1]).toMatchObject({ kind: "word", text: "world" });
    expect(tokens[pauseIndex]).toMatchObject({ kind: "pause", duration_s: 1.3 });
  });

  it("ignores pauses shorter than 1 second", () => {
    const metrics = {
      phrasing: { long_pauses: [{ start_s: 1.0, end_s: 1.4, duration_s: 0.4 }] },
    } as unknown as MetricsReport;
    const tokens = highlightTranscript(buildTranscript(), metrics);
    expect(tokens.some((t) => t.kind === "pause")).toBe(false);
  });

  it("marks a multi-word filler phrase on every word it covers", () => {
    const tokens = highlightTranscript(buildTranscript(), buildMetricsWithPause());
    const you = tokens.find((t) => t.kind === "word" && t.text === "you");
    const know = tokens.find((t) => t.kind === "word" && t.text === "know");
    expect(you?.flags.has("filler")).toBe(true);
    expect(know?.flags.has("filler")).toBe(true);
  });

  it("marks a single-word filler case-insensitively", () => {
    const tokens = highlightTranscript(buildTranscript(), buildMetricsWithPause());
    const so = tokens.find((t) => t.kind === "word" && t.text === "So");
    expect(so?.flags.has("filler")).toBe(true);
  });

  it("marks eaten and low-confidence words by matching start_s", () => {
    const tokens = highlightTranscript(buildTranscript(), buildMetricsWithPause());
    const world = tokens.find((t) => t.kind === "word" && t.text === "world");
    const shipped = tokens.find((t) => t.kind === "word" && t.text === "shipped");
    expect(world?.flags.has("lowconf")).toBe(true);
    expect(shipped?.flags.has("eaten")).toBe(true);
  });

  it("does not flag ordinary words", () => {
    const tokens = highlightTranscript(buildTranscript(), buildMetricsWithPause());
    const hi = tokens.find((t) => t.kind === "word" && t.text === "hi");
    expect(hi?.flags.size).toBe(0);
  });
});
