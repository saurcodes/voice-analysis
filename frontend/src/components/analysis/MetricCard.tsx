import { Warning } from "@phosphor-icons/react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Units that read naturally butted straight against the value ("20.0%", "12.0/min");
 * everything else (word-like units: "Hz", "st", "syl/s") gets a visual gap. */
function isTightUnit(unit: string): boolean {
  return unit === "" || /^[%/]/.test(unit);
}

/** One Summary-tab stat tile: label, big mono value + unit, one-line meaning, and an
 * optional low-confidence badge. Never shown with a null value (see SummaryCards): a
 * metric that couldn't be computed has nothing to call "low confidence" about beyond the
 * already-visible recording_quality QualityBanner. */
export function MetricCard({
  label,
  value,
  unit,
  meaning,
  lowConfidence = false,
  secondary,
}: {
  label: string;
  /** Pre-formatted via fmt()/fmtPercent(); "-" renders as a plain dash, no unit shown. */
  value: string;
  unit: string;
  meaning: string;
  lowConfidence?: boolean;
  /** Extra mono line under the meaning, e.g. "3 words" under a fraction-based card. */
  secondary?: string;
}) {
  const hasValue = value !== "-";

  return (
    <Card>
      <CardContent className="flex flex-col gap-1 px-5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-muted-foreground">{label}</span>
          {hasValue && lowConfidence && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-warning">
              <Warning weight="regular" className="size-3.5" aria-hidden="true" />
              low confidence
            </span>
          )}
        </div>
        <div className="flex items-baseline">
          <span className="num text-2xl font-semibold">{value}</span>
          {hasValue && unit && (
            <span className={cn("text-sm text-muted-foreground", !isTightUnit(unit) && "ml-1.5")}>
              {unit}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{meaning}</p>
        {hasValue && secondary && <p className="num text-xs text-muted-foreground">{secondary}</p>}
      </CardContent>
    </Card>
  );
}
