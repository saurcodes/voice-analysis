/**
 * Small date helpers so the app doesn't need a date library: relativeTime() for the
 * Library table's "Recorded" column (relative text, e.g. "3 days ago"), formatDateTime()
 * for the exact value shown on hover.
 */

const DIVISIONS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 60 * 60 * 24 * 365],
  ["month", 60 * 60 * 24 * 30],
  ["week", 60 * 60 * 24 * 7],
  ["day", 60 * 60 * 24],
  ["hour", 60 * 60],
  ["minute", 60],
];

const relativeTimeFormat = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "3 days ago" / "in 2 hours" / "just now" (anything under a minute). */
export function relativeTime(iso: string): string {
  const diffSec = (Date.parse(iso) - Date.now()) / 1000;

  for (const [unit, secondsInUnit] of DIVISIONS) {
    if (Math.abs(diffSec) >= secondsInUnit) {
      return relativeTimeFormat.format(Math.round(diffSec / secondsInUnit), unit);
    }
  }
  return "just now";
}

const dateTimeFormat = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** "28 Sep 2026, 2:03 PM": the exact timestamp shown on hover over a relative time. */
export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso));
}
