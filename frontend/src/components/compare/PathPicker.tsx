import { METRIC_LABELS } from "@/lib/metrics";
import { Button } from "@/components/ui/button";

/**
 * Toggleable chips, one per comparison row path, used by TrendCharts to pick which metrics to
 * chart. `aria-pressed` carries selection state for assistive tech; the visual state (filled
 * accent vs outline) mirrors it.
 */
export function PathPicker({
  paths,
  selected,
  onToggle,
}: {
  paths: string[];
  selected: string[];
  onToggle: (path: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Metrics to chart">
      {paths.map((path) => {
        const isSelected = selected.includes(path);
        const label = METRIC_LABELS[path]?.label ?? path;
        return (
          <Button
            key={path}
            type="button"
            size="sm"
            variant={isSelected ? "default" : "outline"}
            aria-pressed={isSelected}
            onClick={() => onToggle(path)}
          >
            {label}
          </Button>
        );
      })}
    </div>
  );
}
