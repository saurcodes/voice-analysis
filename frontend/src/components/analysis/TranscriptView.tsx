import { ChatCircleDots, Pause as PauseIcon, Question, TextStrikethrough } from "@phosphor-icons/react";
import type { components } from "@/api/types";
import { cn } from "@/lib/utils";
import { highlightTranscript, type Token, type TranscriptFlag } from "@/lib/metrics";

type MetricsReport = components["schemas"]["MetricsReport"];
type Transcript = components["schemas"]["Transcript"];

const LEGEND_ITEMS: { icon: typeof PauseIcon; label: string }[] = [
  { icon: PauseIcon, label: "Pause" },
  { icon: TextStrikethrough, label: "Eaten word" },
  { icon: Question, label: "Low confidence" },
  { icon: ChatCircleDots, label: "Filler word" },
];

const FLAG_LABEL: Record<TranscriptFlag, string> = {
  filler: "filler word",
  eaten: "eaten word",
  lowconf: "low confidence",
};

/** filler = underlined in the brand accent; eaten = warning-tinted background; low
 * confidence = dotted underline. A word can carry more than one flag (see metrics.ts): the
 * background (eaten) is an independent channel from the underline (filler/lowconf), and
 * when a word is both filler and low-confidence the dotted style wins so the
 * lower-certainty signal stays visible, tinted with the filler's accent color. */
function wordClassName(flags: Set<TranscriptFlag>): string {
  const classes: string[] = [];
  if (flags.has("eaten")) classes.push("bg-[var(--warning)]/15");
  if (flags.has("filler") && flags.has("lowconf")) {
    classes.push("underline decoration-dotted decoration-2 decoration-primary underline-offset-4");
  } else if (flags.has("lowconf")) {
    classes.push("underline decoration-dotted decoration-2 decoration-muted-foreground underline-offset-4");
  } else if (flags.has("filler")) {
    classes.push("underline decoration-solid decoration-2 decoration-primary underline-offset-4");
  }
  return cn(classes);
}

function wordAriaLabel(text: string, flags: Set<TranscriptFlag>): string | undefined {
  if (flags.size === 0) return undefined;
  const order: TranscriptFlag[] = ["filler", "eaten", "lowconf"];
  return order
    .filter((flag) => flags.has(flag))
    .map((flag) => `${FLAG_LABEL[flag]}: ${text}`)
    .join(", ");
}

function WordToken({ token }: { token: Token }) {
  return (
    <span className={wordClassName(token.flags)} aria-label={wordAriaLabel(token.text, token.flags)}>
      {token.text}
    </span>
  );
}

function PauseToken({ token }: { token: Token }) {
  const seconds = (token.duration_s ?? 0).toFixed(1);
  return (
    <span
      className="num mx-0.5 rounded-md border border-border px-1.5 py-0.5 text-xs text-muted-foreground"
      aria-label={`pause ${seconds} seconds`}
    >
      pause {seconds}s
    </span>
  );
}

/** Paragraph flow of the transcript's words, with fillers/eaten/low-confidence words
 * highlighted inline and long pauses rendered as muted chips. Empty state when there is no
 * transcript at all (e.g. a too_short / no_voiced_speech recording). */
export function TranscriptView({
  transcript,
  metrics,
}: {
  transcript: Transcript | null;
  metrics: MetricsReport | null;
}) {
  if (!transcript) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-16 text-center">
        <p className="text-sm text-muted-foreground">No transcript for this recording.</p>
      </div>
    );
  }

  const tokens = highlightTranscript(transcript, metrics);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {LEGEND_ITEMS.map(({ icon: Icon, label }) => (
          <span key={label} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Icon weight="regular" className="size-3.5" aria-hidden="true" />
            {label}
          </span>
        ))}
      </div>

      <p className="max-w-[75ch] text-sm leading-relaxed">
        {tokens.map((token, i) => (
          <span key={i}>
            {token.kind === "pause" ? <PauseToken token={token} /> : <WordToken token={token} />}
            {" "}
          </span>
        ))}
      </p>
    </div>
  );
}
