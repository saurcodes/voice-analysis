import { Waveform } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";

/** Shown instead of the table when the account has no analyses yet. */
export function EmptyLibrary({ onAnalyse }: { onAnalyse: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border py-16 text-center">
      <Waveform weight="regular" className="size-8 text-muted-foreground" />
      <p className="max-w-sm text-sm text-muted-foreground">
        Upload a recording to get your first analysis.
      </p>
      <Button type="button" onClick={onAnalyse}>
        Analyse
      </Button>
    </div>
  );
}
