import type { components } from "@/api/types";
import { cn } from "@/lib/utils";
import { highlightTranscript, type Token, type TranscriptFlag } from "@/lib/metrics";

type MetricsReport = components["schemas"]["MetricsReport"];
type Transcript = components["schemas"]["Transcript"];

const FLAG_LABEL: Record<TranscriptFlag, string> = {
  filler: "filler word",
  eaten: "eaten word",
  lowconf: "low confidence",
};

const FLAG_ORDER: TranscriptFlag[] = ["filler", "eaten", "lowconf"];

/** filler = underlined in the brand accent; eaten = warning-tinted background; low
 * confidence = dotted underline. A word can carry more than one flag (see metrics.ts): the
 * background (eaten) is an independent channel from the underline (filler/lowconf), and
 * when a word is both filler and low-confidence the dotted style wins so the
 * lower-certainty signal stays visible, tinted with the filler's accent color. */
function wordClassName(flags: ReadonlySet<TranscriptFlag>): string {
  const classes: string[] = [];
  if (flags.has("eaten")) classes.push("rounded-sm bg-[var(--warning-fill)]/15");
  if (flags.has("filler") && flags.has("lowconf")) {
    classes.push("underline decoration-dotted decoration-2 decoration-primary underline-offset-4");
  } else if (flags.has("lowconf")) {
    classes.push("underline decoration-dotted decoration-2 decoration-muted-foreground underline-offset-4");
  } else if (flags.has("filler")) {
    classes.push("underline decoration-solid decoration-2 decoration-primary underline-offset-4");
  }
  return cn(classes);
}

const PAUSE_CHIP_CLASS =
  "num mx-0.5 rounded-md border border-border px-1.5 py-0.5 text-xs text-muted-foreground";

/** Each legend entry is a sample word styled exactly like the real marking it explains. */
const LEGEND_ITEMS: { sample: string; flags?: ReadonlySet<TranscriptFlag>; label: string }[] = [
  { sample: "um", flags: new Set<TranscriptFlag>(["filler"]), label: "Filler word" },
  { sample: "word", flags: new Set<TranscriptFlag>(["eaten"]), label: "Eaten word" },
  { sample: "word", flags: new Set<TranscriptFlag>(["lowconf"]), label: "Low confidence" },
  { sample: "pause 1.2s", label: "Pause" },
];

function flagSuffix(flags: ReadonlySet<TranscriptFlag>): string | undefined {
  if (flags.size === 0) return undefined;
  return ` (${FLAG_ORDER.filter((flag) => flags.has(flag))
    .map((flag) => FLAG_LABEL[flag])
    .join(", ")})`;
}

function WordToken({ token }: { token: Token }) {
  const suffix = flagSuffix(token.flags);
  return (
    <span className={wordClassName(token.flags)}>
      {token.text}
      {suffix && <span className="sr-only">{suffix}</span>}
    </span>
  );
}

function PauseToken({ token }: { token: Token }) {
  const seconds = (token.duration_s ?? 0).toFixed(1);
  return (
    <span className={PAUSE_CHIP_CLASS}>
      <span aria-hidden="true">pause {seconds}s</span>
      <span className="sr-only">pause {seconds} seconds</span>
    </span>
  );
}

function EmptyTranscript({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-16 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}

/** Paragraph flow of the transcript's words, with fillers/eaten/low-confidence words
 * highlighted inline and long pauses rendered as muted chips. Empty states when there is no
 * transcript at all (e.g. a too_short / no_voiced_speech recording) and when there is one
 * but it recognised no words (no legend and no pause chips then: there is nothing to mark). */
export function TranscriptView({
  transcript,
  metrics,
}: {
  transcript: Transcript | null;
  metrics: MetricsReport | null;
}) {
  if (!transcript) return <EmptyTranscript message="No transcript for this recording." />;
  if (transcript.words.length === 0) {
    return <EmptyTranscript message="No words were recognised in this recording." />;
  }

  const tokens = highlightTranscript(transcript, metrics);

  return (
    <div className="flex flex-col gap-4">
      <ul aria-label="Legend" className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {LEGEND_ITEMS.map(({ sample, flags, label }) => (
          <li key={label} className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <span
              aria-hidden="true"
              className={flags ? cn("text-sm text-foreground", wordClassName(flags)) : PAUSE_CHIP_CLASS}
            >
              {sample}
            </span>
            {label}
          </li>
        ))}
      </ul>

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
