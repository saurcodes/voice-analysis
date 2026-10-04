import { Fragment } from "react";
import { CheckCircle, Minus, WarningCircle } from "@phosphor-icons/react";
import type { components } from "@/api/types";
import { formatMetricValue, formatSignedDelta, METRIC_LABELS } from "@/lib/metrics";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

type ComparisonResult = components["schemas"]["ComparisonResult"];
type ComparisonRow = components["schemas"]["ComparisonRow"];

const VALID_ARROWS = new Set(["↑", "↓", "→"]); // up, down, right

/** The server's `arrow` field is free text ("up"/"down"/"flat" in practice, not a glyph); use
 * it only when it already is one of the three glyphs the design contract specifies, otherwise
 * derive the glyph from the delta's sign so the column never prints raw server words. */
function arrowGlyph(row: ComparisonRow): string {
  if (VALID_ARROWS.has(row.arrow)) return row.arrow;
  if (row.delta === null || row.delta === 0) return "→";
  return row.delta > 0 ? "↑" : "↓";
}


const GROUP_ORDER: Array<{ prefix: string; label: string }> = [
  { prefix: "pitch", label: "Pitch" },
  { prefix: "phrasing", label: "Phrasing" },
  { prefix: "intonation", label: "Intonation" },
  { prefix: "energy", label: "Energy" },
  { prefix: "articulation", label: "Articulation" },
  { prefix: "transcript", label: "Transcript" },
];

interface RowGroup {
  key: string;
  label: string;
  rows: ComparisonRow[];
}

/** Groups by the path's first segment, in the fixed display order Pitch / Phrasing /
 * Intonation / Energy / Articulation / Transcript; rows keep server order within a group.
 * Any future path with an unrecognised first segment still renders, in an "Other" group
 * appended at the end, rather than silently disappearing. */
function groupRows(rows: ComparisonRow[]): RowGroup[] {
  const known = new Set(GROUP_ORDER.map((g) => g.prefix));
  const groups: RowGroup[] = GROUP_ORDER.map((g) => ({
    key: g.prefix,
    label: g.label,
    rows: rows.filter((row) => row.path.split(".")[0] === g.prefix),
  }));
  const otherRows = rows.filter((row) => !known.has(row.path.split(".")[0]));
  if (otherRows.length > 0) groups.push({ key: "other", label: "Other", rows: otherRows });
  return groups.filter((g) => g.rows.length > 0);
}

function VerdictCell({ row }: { row: ComparisonRow }) {
  if (row.verdict === "unavailable") {
    return (
      <span className="num flex items-center gap-1.5 text-sm text-muted-foreground">
        <span>-</span>
        <span>n/a</span>
      </span>
    );
  }

  const delta = formatSignedDelta(METRIC_LABELS[row.path], row.delta);
  // A delta that rounds to "0.0" reads as no movement, whatever the server's arrow says.
  const arrow = delta.isZero ? "→" : arrowGlyph(row);

  let icon = <Minus weight="regular" className="size-3.5 text-muted-foreground" aria-hidden="true" />;
  let verdictText = "Changed";
  let verdictClassName = "text-muted-foreground";

  if (row.verdict === "improved") {
    // Verdict icons say good/bad, not direction: the arrow beside the delta carries direction
    // (a lower filler rate is "Improved" with a down arrow).
    icon = <CheckCircle weight="regular" className="size-3.5 text-good" aria-hidden="true" />;
    verdictText = "Improved";
    verdictClassName = "text-good";
  } else if (row.verdict === "worsened") {
    icon = <WarningCircle weight="regular" className="size-3.5 text-serious" aria-hidden="true" />;
    verdictText = "Worsened";
    verdictClassName = "text-serious";
  } else if (row.verdict === "unchanged") {
    verdictText = "No change";
  }

  return (
    <div className="flex flex-col gap-0.5">
      <span className="num text-sm">
        {delta.text} {arrow}
      </span>
      <span className={`flex items-center gap-1 text-xs ${verdictClassName}`}>
        {icon}
        {verdictText}
      </span>
    </div>
  );
}

function MetricCell({ row }: { row: ComparisonRow }) {
  const label = METRIC_LABELS[row.path];
  return (
    <div className="flex items-center gap-2">
      <div className="flex flex-col">
        <span className="text-sm font-medium">{label?.label ?? row.path}</span>
        {label?.unit && <span className="text-xs text-muted-foreground">{label.unit}</span>}
      </div>
      {row.partial && (
        <Tooltip>
          <TooltipTrigger asChild>
            {/* tabIndex makes the badge keyboard-focusable so the tooltip is not hover-only. */}
            <Badge
              tabIndex={0}
              variant="outline"
              className="border-[var(--warning-fill)]/40 bg-[var(--warning-fill)]/10 text-warning"
            >
              <WarningCircle weight="regular" aria-hidden="true" />
              gaps
            </Badge>
          </TooltipTrigger>
          <TooltipContent>
            Some recordings lack this metric; change computed from the available ones.
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

/**
 * One row per comparison path, grouped by metric section with a subtle group header, one
 * value column per recording (null -> "-", aria-label "not available") and a Change column
 * (signed delta + arrow glyph, verdict as icon + text). Rows are separated by the Table
 * primitive's existing hairline border per row (no per-cell borders).
 */
export function ComparisonTable({
  comparison,
  recordingNames,
}: {
  comparison: ComparisonResult;
  recordingNames: string[];
}) {
  const groups = groupRows(comparison.rows);
  const columnCount = recordingNames.length + 2;

  return (
    <TooltipProvider>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Metric</TableHead>
            {comparison.analysis_ids.map((id, i) => (
              <TableHead key={id}>{recordingNames[i]}</TableHead>
            ))}
            <TableHead>Change</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.map((group) => (
            <Fragment key={group.key}>
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={columnCount}
                  className="bg-muted/30 py-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase"
                >
                  {group.label}
                </TableCell>
              </TableRow>
              {group.rows.map((row) => {
                const label = METRIC_LABELS[row.path];
                return (
                  <TableRow key={row.path}>
                    <TableCell>
                      <MetricCell row={row} />
                    </TableCell>
                    {row.values.map((value, i) => (
                      <TableCell key={`${row.path}-${i}`} className="num">
                        {value === null ? (
                          <span aria-label="not available">-</span>
                        ) : (
                          formatMetricValue(label, value)
                        )}
                      </TableCell>
                    ))}
                    <TableCell>
                      <VerdictCell row={row} />
                    </TableCell>
                  </TableRow>
                );
              })}
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </TooltipProvider>
  );
}
