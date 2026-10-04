import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { components } from "@/api/types";
import { fmt, formatClockTime, isTimelineEmpty } from "@/lib/metrics";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type MetricsReport = components["schemas"]["MetricsReport"];
type TimelineWindow = components["schemas"]["TimelineWindow"];

interface ChartSpec {
  dataKey: "f0_median_hz" | "f0_sd_st" | "intensity_median_db";
  title: string;
  unit: string;
  digits: number;
}

/** Three small multiples, one y-axis each (per the dataviz method: never dual-axis). */
const CHARTS: ChartSpec[] = [
  { dataKey: "f0_median_hz", title: "F0 median", unit: "Hz", digits: 0 },
  { dataKey: "f0_sd_st", title: "F0 variation", unit: "st", digits: 1 },
  { dataKey: "intensity_median_db", title: "Intensity", unit: "dB", digits: 1 },
];

const AXIS_TICK = { fill: "var(--muted-foreground)", fontSize: 11 };

/** Crosshair tooltip: window range + value, both in .num text tokens (never the series
 * color, per marks-and-anatomy.md's "text never wears the data color"). */
function ChartTooltip({
  active,
  payload,
  unit,
  digits,
}: TooltipContentProps<number, string> & { unit: string; digits: number }) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload as TimelineWindow;
  const rawValue = payload[0].value;
  const value = typeof rawValue === "number" ? rawValue : null;

  return (
    <div className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs shadow-sm">
      <p className="num text-muted-foreground">
        {formatClockTime(point.start_s)} to {formatClockTime(point.end_s)}
      </p>
      <p className="num font-medium text-foreground">
        {fmt(value, digits)} {unit}
      </p>
    </div>
  );
}

function TimelineTable({ windows }: { windows: TimelineWindow[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Start</TableHead>
          <TableHead>End</TableHead>
          <TableHead>F0 median Hz</TableHead>
          <TableHead>F0 variation st</TableHead>
          <TableHead>Intensity dB</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {windows.map((window, i) => (
          <TableRow key={i}>
            <TableCell className="num">{formatClockTime(window.start_s)}</TableCell>
            <TableCell className="num">{formatClockTime(window.end_s)}</TableCell>
            <TableCell className="num">{fmt(window.f0_median_hz, 0)}</TableCell>
            <TableCell className="num">{fmt(window.f0_sd_st)}</TableCell>
            <TableCell className="num">{fmt(window.intensity_median_db)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** F0 median / F0 variation / Intensity per timeline window, each its own small-multiple
 * line chart, plus a "Show as table" toggle that swaps all three for one Table of the same
 * windows (dataviz's "every chart has a table-view twin"). */
export function TimelineCharts({ metrics }: { metrics: MetricsReport }) {
  const [showTable, setShowTable] = useState(false);
  const windows = metrics.timeline.windows;
  const windowS = metrics.timeline.window_s;

  if (isTimelineEmpty(metrics)) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-16 text-center">
        <p className="text-sm text-muted-foreground">Not enough voiced speech for a timeline.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Button type="button" variant="ghost" size="sm" onClick={() => setShowTable((prev) => !prev)}>
          {showTable ? "Show as charts" : "Show as table"}
        </Button>
      </div>

      {showTable ? (
        <TimelineTable windows={windows} />
      ) : (
        <div className="flex flex-col gap-6">
          {CHARTS.map((chart) => (
            <figure
              key={chart.dataKey}
              role="img"
              aria-label={`${chart.title} per ${windowS} second window`}
            >
              <figcaption className="mb-2 text-sm font-medium">
                {chart.title} <span className="text-muted-foreground">({chart.unit})</span>
              </figcaption>
              <ResponsiveContainer width="100%" height={160}>
                <LineChart data={windows} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="start_s"
                    tickFormatter={(value: number) => formatClockTime(value)}
                    stroke="var(--border)"
                    tick={AXIS_TICK}
                    tickLine={false}
                  />
                  <YAxis width={40} tickCount={4} stroke="var(--border)" tick={AXIS_TICK} tickLine={false} />
                  <Tooltip
                    content={(props) => (
                      <ChartTooltip {...props} unit={chart.unit} digits={chart.digits} />
                    )}
                    cursor={{ stroke: "var(--border)" }}
                  />
                  <Line
                    type="monotone"
                    dataKey={chart.dataKey}
                    stroke="var(--accent)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}
