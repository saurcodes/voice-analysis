import { Warning } from "@phosphor-icons/react";
import { Alert, AlertDescription } from "@/components/ui/alert";

/**
 * Shown above the Compare page's table whenever the comparison carries a config or analyser
 * version mismatch (ComparisonResult.config_mismatch / analyser_version_mismatch). Both can
 * show at once (e.g. the same two recordings were analysed with different settings AND a
 * different analyser build). Warning colour + icon + text, never colour alone.
 */
export function MismatchBanners({
  configMismatch,
  analyserVersionMismatch,
}: {
  configMismatch: boolean;
  analyserVersionMismatch: boolean;
}) {
  if (!configMismatch && !analyserVersionMismatch) return null;

  return (
    <div className="flex flex-col gap-2">
      {configMismatch && (
        <Alert className="border-[var(--warning-fill)]/40 bg-[var(--warning-fill)]/10">
          <Warning weight="regular" className="text-warning" aria-hidden="true" />
          <AlertDescription className="text-foreground">
            These recordings were analysed with different settings; deltas may not be comparable.
          </AlertDescription>
        </Alert>
      )}
      {analyserVersionMismatch && (
        <Alert className="border-[var(--warning-fill)]/40 bg-[var(--warning-fill)]/10">
          <Warning weight="regular" className="text-warning" aria-hidden="true" />
          <AlertDescription className="text-foreground">
            Different analyser versions; numbers may differ for reasons other than your speaking.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
