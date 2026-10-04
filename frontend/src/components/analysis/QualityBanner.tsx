import { Warning } from "@phosphor-icons/react";

const REASON_TEXT: Record<string, string> = {
  too_short: "Recording shorter than 2 seconds; no metrics computed.",
  no_voiced_speech: "No voiced speech detected.",
  low_snr: "Noisy recording; voice-quality and articulation metrics are low confidence.",
  high_noise_floor: "Noisy recording; voice-quality and articulation metrics are low confidence.",
};

/** Shown above the Summary tab whenever metrics.recording_quality.reasons is non-empty.
 * Known reasons get plain-language text; an unrecognised reason (future analyser version)
 * falls back to the raw string rather than disappearing silently. */
export function QualityBanner({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null;

  const messages = Array.from(new Set(reasons.map((reason) => REASON_TEXT[reason] ?? reason)));

  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-4 py-3"
    >
      <Warning weight="regular" className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
      <div className="flex flex-col gap-0.5 text-sm text-foreground">
        {messages.map((message) => (
          <p key={message}>{message}</p>
        ))}
      </div>
    </div>
  );
}
