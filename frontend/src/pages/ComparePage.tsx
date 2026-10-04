import { Link, useSearchParams } from "react-router";
import { ApiError } from "@/api/client";
import { useComparison, useSummaries } from "@/api/hooks";
import { AppShell } from "@/components/AppShell";
import { ComparisonTable } from "@/components/compare/ComparisonTable";
import { MismatchBanners } from "@/components/compare/MismatchBanners";
import { TrendCharts } from "@/components/compare/TrendCharts";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDateTime } from "@/lib/dates";

/** Fixed categorical slots, assigned in order, never cycled (dataviz color-formula.md). Mirrors
 * TrendCharts' own CHART_COLORS so the header swatch matches the chart that recording appears
 * in. */
const CHART_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"];

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
 * <=3 most recent, by recorded_at), in chronological slot order - see the ruling in
 * TrendCharts.tsx's pickChartRecordings(). Ids outside that set (when there are >3 recordings)
 * get no swatch, since they are not plotted in any chart. */
function chartColorsById(ids: string[], recordedAt: string[]): Record<string, string> {
  const all = ids.map((id, i) => ({ id, recordedAt: recordedAt[i] }));
  const mostRecentFirst = [...all].sort((a, b) => Date.parse(b.recordedAt) - Date.parse(a.recordedAt));
  const chartedIds = new Set(mostRecentFirst.slice(0, 3).map((r) => r.id));
  const chronological = mostRecentFirst
    .filter((r) => chartedIds.has(r.id))
    .sort((a, b) => Date.parse(a.recordedAt) - Date.parse(b.recordedAt));
  const colors: Record<string, string> = {};
  chronological.forEach((r, i) => {
    colors[r.id] = CHART_COLORS[i];
  });
  return colors;
}

export function ComparePage() {
  const [searchParams] = useSearchParams();
  const ids = parseIds(searchParams.get("ids"));

  const comparisonQuery = useComparison(ids);
  const summariesQuery = useSummaries({ limit: 200 });

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

  if (comparisonQuery.isLoading || summariesQuery.isLoading) {
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

  const summaries = summariesQuery.data ?? [];
  const namesById: Record<string, string> = {};
  for (const s of summaries) namesById[s.id] = s.file_name;

  const recordingNames = comparison.analysis_ids.map((id) => namesById[id] ?? id.slice(0, 8));
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
