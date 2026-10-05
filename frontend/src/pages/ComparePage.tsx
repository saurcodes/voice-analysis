import { Link, useSearchParams } from "react-router";
import { ApiError } from "@/api/client";
import { useComparison } from "@/api/hooks";
import { AppShell } from "@/components/AppShell";
import { ComparisonTable } from "@/components/compare/ComparisonTable";
import { MismatchBanners } from "@/components/compare/MismatchBanners";
import { TrendCharts } from "@/components/compare/TrendCharts";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { chartSlots } from "@/lib/compare";
import { formatDateTime } from "@/lib/dates";

function errorDetail(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === "string") return error.detail;
  return "Something went wrong. Try again.";
}

function parseIds(raw: string | null): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);
}

function HeaderSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <Skeleton className="h-6 w-48" />
      <div className="flex flex-wrap gap-4">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-5 w-40" />
      </div>
    </div>
  );
}

function TableSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: 6 }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

/** Returns a color per analysis_id for the ids that will actually appear in TrendCharts (the
 * <=3 most recent, by recorded_at), via the shared chartSlots() helper so the header swatch
 * always matches the chart that recording appears in. Ids outside that set (when there are
 * >3 recordings) get no swatch, since they are not plotted in any chart. */
function chartColorsById(ids: string[], recordedAt: string[]): Record<string, string> {
  const colors: Record<string, string> = {};
  for (const slot of chartSlots(ids, recordedAt)) colors[slot.id] = slot.color;
  return colors;
}

export function ComparePage() {
  const [searchParams] = useSearchParams();
  const ids = parseIds(searchParams.get("ids"));

  const comparisonQuery = useComparison(ids);

  if (ids.length < 2) {
    return (
      <AppShell>
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">
            Select two or more recordings in the Library to compare them.
          </p>
          <Button type="button" variant="outline" asChild>
            <Link to="/">Back to Library</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  if (comparisonQuery.isLoading) {
    return (
      <AppShell>
        <div className="flex flex-col gap-6">
          <HeaderSkeleton />
          <TableSkeleton />
        </div>
      </AppShell>
    );
  }

  if (comparisonQuery.isError) {
    const error = comparisonQuery.error;
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <AppShell>
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">
            {notFound ? "One of these recordings was not found." : errorDetail(error)}
          </p>
          <Button type="button" variant="outline" asChild>
            <Link to="/">Back to Library</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  const comparison = comparisonQuery.data;
  if (!comparison) return null;

  // file_names is positional with analysis_ids; a null slot (unknown file name) falls back to
  // the id prefix.
  const recordingNames = comparison.analysis_ids.map(
    (id, i) => comparison.file_names[i] ?? id.slice(0, 8),
  );
  const namesById: Record<string, string> = {};
  comparison.analysis_ids.forEach((id, i) => {
    namesById[id] = recordingNames[i];
  });
  const colorsById = chartColorsById(comparison.analysis_ids, comparison.recorded_at);

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Compare recordings</h1>
          <ul className="flex flex-wrap gap-x-6 gap-y-2">
            {comparison.analysis_ids.map((id, i) => (
              <li key={id} className="flex items-center gap-2 text-sm">
                {colorsById[id] && (
                  <span
                    className="size-3 shrink-0 rounded-sm"
                    style={{ backgroundColor: colorsById[id] }}
                    aria-hidden="true"
                  />
                )}
                <span className="font-medium">{recordingNames[i]}</span>
                <span className="num text-muted-foreground">
                  {formatDateTime(comparison.recorded_at[i])}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <MismatchBanners
          configMismatch={comparison.config_mismatch}
          analyserVersionMismatch={comparison.analyser_version_mismatch}
        />

        <ComparisonTable comparison={comparison} recordingNames={recordingNames} />

        <TrendCharts comparison={comparison} names={namesById} />
      </div>
    </AppShell>
  );
}
