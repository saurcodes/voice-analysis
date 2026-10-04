import { chartSlots, CHART_COLORS } from "./compare";

test("keeps the 3 most recent recordings, slotted chronologically, dropping the oldest", () => {
  const ids = ["a", "b", "c", "d"];
  const recordedAt = [
    "2026-01-01T00:00:00Z", // a: 2nd most recent
    "2026-03-01T00:00:00Z", // b: most recent
    "2026-02-01T00:00:00Z", // c: 3rd most recent
    "2025-12-01T00:00:00Z", // d: oldest, dropped (only 3 recordings get charted)
  ];

  const slots = chartSlots(ids, recordedAt);

  // Chronological (oldest-first) order among the 3 most recent: a, c, b. d is excluded.
  expect(slots.map((s) => s.id)).toEqual(["a", "c", "b"]);
  expect(slots.map((s) => s.slot)).toEqual([1, 2, 3]);
  expect(slots.map((s) => s.color)).toEqual(CHART_COLORS);
  expect(slots.find((s) => s.id === "d")).toBeUndefined();
});

test("recordings given out of request order are still returned chronologically, with all <=3 kept", () => {
  const ids = ["newer", "older"];
  const recordedAt = ["2026-02-01T00:00:00Z", "2026-01-01T00:00:00Z"];

  const slots = chartSlots(ids, recordedAt);

  expect(slots.map((s) => s.id)).toEqual(["older", "newer"]);
  expect(slots.map((s) => s.slot)).toEqual([1, 2]);
  expect(slots.map((s) => s.color)).toEqual([CHART_COLORS[0], CHART_COLORS[1]]);
});
