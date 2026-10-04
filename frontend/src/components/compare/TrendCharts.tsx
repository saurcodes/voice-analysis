import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type ActiveDotProps,
  type DotItemDotProps,
  type TooltipContentProps,
} from "recharts";
import type { components } from "@/api/types";
import { formatMetricValue, METRIC_LABELS, type MetricLabel } from "@/lib/metrics";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PathPicker } from "./PathPicker";

type ComparisonResult = components["schemas"]["ComparisonResult"];
type TrendPoint = components["schemas"]["TrendPoint"];

/** Fixed categorical slots, assigned in order, never cycled (dataviz color-formula.md). */
const CHART_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"];
const AXIS_TICK = { fill: "var(--muted-foreground)", fontSize: 11 };
const dayMonthFormat = new Intl.DateTimeFormat("en", { day: "numeric", month: "short" });

/** The brief's default 4 trend chips, chosen for every comparison regardless of which paths
 * the server actually returned for this pair of recordings. */
const DEFAULT_TREND_PATHS = [
  "pitch.f0_range_st",
  "intonation.flat_pct",
  "phrasing.pauses_per_min",
  "transcript.derived.fillers_per_min",
];

interface ChartRecording {
  id: string;
  recordedAt: string;
  name: string;
  color: string;
}

interface ChartPoint {
  id: string;
  name: string;
  recordedAt: string;
  value: number | null;
  color: string;
}

/** Picks the <=3 most recent recordings (by recorded_at) and returns them in chronological
 * order with slot colours assigned chart-1..3 in that order, per the controller ruling:
 * "slot colours follow the chart's 3 recordings in chronological order." */
function pickChartRecordings(
  ids: string[],
  recordedAt: string[],
  names: Record<string, string>,
): ChartRecording[] {
  const all = ids.map((id, i) => ({ id, recordedAt: recordedAt[i] }));
  const mostRecentFirst = [...all].sort(
    (a, b) => Date.parse(b.recordedAt) - Date.parse(a.recordedAt),
  );
  const chosen = mostRecentFirst.slice(0, 3);
  const chronological = chosen.sort((a, b) => Date.parse(a.recordedAt) - Date.parse(b.recordedAt));
  return chronological.map((r, i) => ({
    ...r,
    name: names[r.id] ?? r.id.slice(0, 8),
    color: CHART_COLORS[i],
  }));
}

/** Named defaults first (in the brief's order), padded with whatever other row paths are
 * available until there are 4 selected (or fewer, if the comparison has under 4 rows total).
 * Needed because a given pair of recordings' rows may not include all 4 named defaults. */
function defaultSelection(availablePaths: string[]): string[] {
  const named = DEFAULT_TREND_PATHS.filter((path) => availablePaths.includes(path));
  const rest = availablePaths.filter((path) => !named.includes(path));
  return [...named, ...rest].slice(0, Math.min(4, availablePaths.length));
}

function buildChartData(
  path: string,
  trend: Record<string, TrendPoint[]>,
  chartRecordings: ChartRecording[],
): ChartPoint[] {
  const byId = new Map((trend[path] ?? []).map((point) => [point.analysis_id, point.value]));
  return chartRecordings.map((r) => ({
    id: r.id,
    name: r.name,
    recordedAt: r.recordedAt,
    value: byId.has(r.id) ? (byId.get(r.id) ?? null) : null,
    color: r.color,
  }));
}

function ChartLegend({ recordings }: { recordings: ChartRecording[] }) {
  return (
    <div className="flex flex-wrap items-center gap-3 pt-1 text-xs text-muted-foreground">
      {recordings.map((r) => (
        <span key={r.id} className="flex items-center gap-1.5">
          <span className="size-3 rounded-sm" style={{ backgroundColor: r.color }} aria-hidden="true" />
          {r.name}
        </span>
      ))}
    </div>
  );
}

/** Filled in the point's recording slot colour, >=8px (r=5 -> 10px), with a surface ring so it
 * stays legible crossing the connector line (marks-and-anatomy.md). Returns null on a gap
 * point so nulls read as a gap, not a zero. */
function TrendDot(props: DotItemDotProps) {
  const { cx, cy, payload } = props;
  const point = payload as ChartPoint;
  if (cx === undefined || cy === undefined || point.value === null) return null;
  return <circle cx={cx} cy={cy} r={5} fill={point.color} stroke="var(--background)" strokeWidth={2} />;
}

function TrendActiveDot(props: ActiveDotProps) {
  const { cx, cy, payload } = props;
  const point = payload as ChartPoint;
  if (cx === undefined || cy === undefined || point.value === null) return null;
  return <circle cx={cx} cy={cy} r={6} fill={point.color} stroke="var(--background)" strokeWidth={2} />;
}

/** Factory rather than a component typed with an extra `label` prop: recharts' `content`
 * overloads unify the render function's prop type against its own generic value/name types,
 * and intersecting that with an unrelated object type (MetricLabel) breaks that inference.
 * Capturing `label` in a closure keeps the rendered function's signature exactly
 * TooltipContentProps<number, string>, which the overload matches cleanly. */
function makeTrendTooltip(label: MetricLabel | undefined) {
  return function TrendTooltip({ active, payload }: TooltipContentProps<number, string>) {
    if (!active || !payload || payload.length === 0) return null;
    const point = payload[0].payload as ChartPoint;

    return (
      <div className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs shadow-sm">
        <p className="text-foreground">{point.name}</p>
        <p className="num text-muted-foreground">{dayMonthFormat.format(new Date(point.recordedAt))}</p>
        <p className="num font-medium text-foreground">
          {point.value === null ? "-" : formatMetricValue(label, point.value)} {label?.unit}
        </p>
      </div>
    );
  };
}

function TrendTable({
  paths,
  chartRecordings,
  trend,
}: {
  paths: string[];
  chartRecordings: ChartRecording[];
  trend: Record<string, TrendPoint[]>;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Metric</TableHead>
          {chartRecordings.map((r) => (
            <TableHead key={r.id} className="num">
              {r.name}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {paths.map((path) => {
          const label = METRIC_LABELS[path];
          const byId = new Map((trend[path] ?? []).map((point) => [point.analysis_id, point.value]));
          return (
            <TableRow key={path}>
              <TableCell>
                {label?.label ?? path}
                {label?.unit && <span className="text-muted-foreground"> ({label.unit})</span>}
              </TableCell>
              {chartRecordings.map((r) => {
                const value = byId.has(r.id) ? (byId.get(r.id) ?? null) : null;
                return (
                  <TableCell key={r.id} className="num">
                    {value === null ? <span aria-label="not available">-</span> : formatMetricValue(label, value)}
                  </TableCell>
                );
              })}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

/**
 * PathPicker chips (default 4) plus one small-multiple line chart per picked path: x =
 * recorded date (chronological), one line (the metric's trajectory across the compared
 * recordings), each point filled in its recording's fixed slot colour so identity rides the
 * legend row beneath the chart. Capped at the 3 most recent recordings when there are more.
 */
export function TrendCharts({
  comparison,
  names,
}: {
  comparison: ComparisonResult;
  names: Record<string, string>;
}) {
  const availablePaths = useMemo(() => comparison.rows.map((row) => row.path), [comparison.rows]);
  const [selected, setSelected] = useState<string[]>(() => defaultSelection(availablePaths));
  const [showTable, setShowTable] = useState(false);

  const chartRecordings = useMemo(
    () => pickChartRecordings(comparison.analysis_ids, comparison.recorded_at, names),
    [comparison.analysis_ids, comparison.recorded_at, names],
  );
  const hasMoreThanThree = comparison.analysis_ids.length > 3;

  function toggle(path: string) {
    setSelected((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PathPicker paths={availablePaths} selected={selected} onToggle={toggle} />
        <Button type="button" variant="ghost" size="sm" onClick={() => setShowTable((prev) => !prev)}>
          {showTable ? "Show as charts" : "Show as table"}
        </Button>
      </div>

      {hasMoreThanThree && (
        <p className="text-xs text-muted-foreground">Showing the 3 most recent recordings</p>
      )}

      {selected.length === 0 ? (
        <p className="text-sm text-muted-foreground">Pick a metric above to chart it.</p>
      ) : showTable ? (
        <TrendTable paths={selected} chartRecordings={chartRecordings} trend={comparison.trend} />
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          {selected.map((path) => {
            const label = METRIC_LABELS[path];
            const data = buildChartData(path, comparison.trend, chartRecordings);
            const title = label?.label ?? path;
            return (
              <figure key={path} role="img" aria-label={`${title} across recordings`}>
                <figcaption className="mb-2 text-sm font-medium">
                  {title} {label?.unit && <span className="text-muted-foreground">({label.unit})</span>}
                </figcaption>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke="var(--border)" vertical={false} />
                    <XAxis
                      dataKey="recordedAt"
                      tickFormatter={(value: string) => dayMonthFormat.format(new Date(value))}
                      stroke="var(--border)"
                      tick={AXIS_TICK}
                      tickLine={false}
                    />
                    <YAxis width={44} tickCount={4} stroke="var(--border)" tick={AXIS_TICK} tickLine={false} />
                    <Tooltip content={makeTrendTooltip(label)} cursor={{ stroke: "var(--border)" }} />
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke="var(--muted-foreground)"
                      strokeWidth={2}
                      dot={(props: DotItemDotProps) => <TrendDot {...props} />}
                      activeDot={(props: ActiveDotProps) => <TrendActiveDot {...props} />}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
                <ChartLegend recordings={chartRecordings} />
              </figure>
            );
          })}
        </div>
      )}
    </div>
  );
}
