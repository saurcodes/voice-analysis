import type { components } from "@/api/types";
import { fmt, fmtPercent, METRIC_LABELS } from "@/lib/metrics";
import { MetricCard } from "./MetricCard";
import { QualityBanner } from "./QualityBanner";

type MetricsReport = components["schemas"]["MetricsReport"];
type Transcript = components["schemas"]["Transcript"];

/**
 * The 8 Summary stat tiles plus the recording-quality banner. Low-confidence badges are
 * sourced from the schema's own low_confidence flags: PitchBlock itself carries none, so
 * the two pitch-derived cards (median pitch, pitch range) fall back to
 * voice_quality.low_confidence, which is exactly the signal (jitter/shimmer/HNR estimation
 * failure) that undermines F0 tracking; the articulation-rate card falls back to
 * articulation.low_confidence for the same reason (no low_confidence flag lives on
 * PaceBlock, where articulation_rate_syl_per_sec actually comes from). The remaining 5
 * cards (flat endings, pauses/min, trailing off, fillers/min, eaten words) have no
 * corresponding low_confidence signal anywhere in MetricsReport/DerivedBlock, so they
 * never show the badge; page-wide quality issues still surface via QualityBanner.
 */
export function SummaryCards({
  metrics,
  transcript,
}: {
  metrics: MetricsReport;
  transcript: Transcript | null;
}) {
  const pitchLowConfidence = metrics.voice_quality.low_confidence;
  const articulationLowConfidence = metrics.articulation.low_confidence;

  const eatenCount = transcript?.derived.clarity.eaten_words.length ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <QualityBanner reasons={metrics.recording_quality.reasons} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label={METRIC_LABELS["pitch.f0_median_hz"].label}
          unit={METRIC_LABELS["pitch.f0_median_hz"].unit}
          meaning={METRIC_LABELS["pitch.f0_median_hz"].meaning}
          value={fmt(metrics.pitch.f0_median_hz, 0)}
          lowConfidence={pitchLowConfidence}
        />
        <MetricCard
          label={METRIC_LABELS["pitch.f0_range_st"].label}
          unit={METRIC_LABELS["pitch.f0_range_st"].unit}
          meaning={METRIC_LABELS["pitch.f0_range_st"].meaning}
          value={fmt(metrics.pitch.f0_range_st)}
          lowConfidence={pitchLowConfidence}
        />
        <MetricCard
          label={METRIC_LABELS["intonation.flat_pct"].label}
          unit={METRIC_LABELS["intonation.flat_pct"].unit}
          meaning={METRIC_LABELS["intonation.flat_pct"].meaning}
          value={fmt(metrics.intonation.flat_pct)}
        />
        <MetricCard
          label={METRIC_LABELS["phrasing.pauses_per_min"].label}
          unit={METRIC_LABELS["phrasing.pauses_per_min"].unit}
          meaning={METRIC_LABELS["phrasing.pauses_per_min"].meaning}
          value={fmt(metrics.phrasing.pauses_per_min)}
        />
        <MetricCard
          label={METRIC_LABELS["pace.articulation_rate_syl_per_sec"].label}
          unit={METRIC_LABELS["pace.articulation_rate_syl_per_sec"].unit}
          meaning={METRIC_LABELS["pace.articulation_rate_syl_per_sec"].meaning}
          value={fmt(metrics.pace.articulation_rate_syl_per_sec)}
          lowConfidence={articulationLowConfidence}
        />
        <MetricCard
          label={METRIC_LABELS["energy.trailing_off_count"].label}
          unit={METRIC_LABELS["energy.trailing_off_count"].unit}
          meaning={METRIC_LABELS["energy.trailing_off_count"].meaning}
          value={fmt(metrics.energy.trailing_off_count, 0)}
        />
        <MetricCard
          label={METRIC_LABELS["transcript.derived.fillers_per_min"].label}
          unit={METRIC_LABELS["transcript.derived.fillers_per_min"].unit}
          meaning={METRIC_LABELS["transcript.derived.fillers_per_min"].meaning}
          value={fmt(transcript?.derived.fillers_per_min ?? null)}
        />
        <MetricCard
          label={METRIC_LABELS["transcript.derived.clarity.word_final_drop_fraction"].label}
          unit={METRIC_LABELS["transcript.derived.clarity.word_final_drop_fraction"].unit}
          meaning={METRIC_LABELS["transcript.derived.clarity.word_final_drop_fraction"].meaning}
          value={fmtPercent(transcript?.derived.clarity.word_final_drop_fraction ?? null)}
          secondary={transcript ? `${eatenCount} word${eatenCount === 1 ? "" : "s"}` : undefined}
        />
      </div>
    </div>
  );
}
