/**
 * Shared "which recordings get a chart colour, and which colour" logic for the Compare page.
 * Both the page header (recording swatches) and TrendCharts (chart lines + legend) need the
 * same answer - the <=3 most recent recordings, in chronological order, slotted onto the
 * fixed --chart-1/2/3 categorical colours (dataviz color-formula.md: fixed slot order, never
 * cycled) - so this is the one place that sort+slice+sort lives, instead of two copies that
 * could quietly drift apart.
 */

export const CHART_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)"];

export interface ChartSlot {
  id: string;
  recordedAt: string;
  /** 1-based slot index (1, 2, or 3). */
  slot: number;
  /** The var(--chart-N) value assigned to this slot. */
  color: string;
}

/**
 * Picks the <=3 most recent recordings (by recorded_at) out of every id/recordedAt pair
 * given, and returns just that charted subset in chronological (oldest-first) order with
 * slot 1..3 and a fixed --chart-N colour assigned in that chronological order. Recordings
 * outside the charted set (when there are more than 3 total) are simply absent from the
 * result - callers treat a missing id as "no swatch for this one, it isn't plotted."
 */
export function chartSlots(ids: string[], recordedAt: string[]): ChartSlot[] {
  const all = ids.map((id, i) => ({ id, recordedAt: recordedAt[i] }));
  const mostRecentFirst = [...all].sort((a, b) => Date.parse(b.recordedAt) - Date.parse(a.recordedAt));
  const charted = mostRecentFirst.slice(0, 3);
  const chronological = charted.sort((a, b) => Date.parse(a.recordedAt) - Date.parse(b.recordedAt));
  return chronological.map((r, i) => ({ ...r, slot: i + 1, color: CHART_COLORS[i] }));
}
