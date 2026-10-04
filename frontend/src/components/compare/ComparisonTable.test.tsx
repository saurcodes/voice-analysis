import { act, screen, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { comparison } from "@/test/fixtures";
import { ComparisonTable } from "./ComparisonTable";

function renderTable() {
  const data = comparison();
  renderWithProviders(<ComparisonTable comparison={data} recordingNames={["Take 1", "Take 2"]} />);
  return data;
}

test("groups rows under their metric section headers in server row order", () => {
  renderTable();

  // Groups present for this fixture's paths, in the fixed Pitch/Phrasing/.../Transcript order.
  expect(screen.getByText("Pitch")).toBeInTheDocument();
  expect(screen.getByText("Phrasing")).toBeInTheDocument();
  expect(screen.getByText("Articulation")).toBeInTheDocument();
  expect(screen.getByText("Transcript")).toBeInTheDocument();
  // No Intonation or Energy rows in this fixture, so no such group header.
  expect(screen.queryByText("Intonation")).not.toBeInTheDocument();
  expect(screen.queryByText("Energy")).not.toBeInTheDocument();
});

test("improved row shows the signed delta and arrow derived from the delta sign, plus verdict icon + text, values in mono", () => {
  renderTable();

  const row = screen.getByText("Pitch range").closest("tr");
  expect(row).not.toBeNull();
  const scoped = within(row!);

  expect(scoped.getByText("8.2")).toHaveClass("num");
  expect(scoped.getByText("10.8")).toHaveClass("num");
  expect(scoped.getByText(/\+2\.6/)).toBeInTheDocument();
  expect(scoped.getByText(/↑/)).toBeInTheDocument();
  expect(scoped.getByText("Improved")).toBeInTheDocument();
});

test("unavailable row shows n/a with no arrow, plus the gaps badge for its partial flag", () => {
  renderTable();

  const row = screen.getByText("Weak syllable peaks").closest("tr");
  expect(row).not.toBeNull();
  const scoped = within(row!);

  expect(scoped.getByText("n/a")).toBeInTheDocument();
  expect(scoped.queryByText(/[↑↓→]/)).not.toBeInTheDocument();
  expect(scoped.queryByText("Improved")).not.toBeInTheDocument();
  expect(scoped.queryByText("Worsened")).not.toBeInTheDocument();

  expect(scoped.getByText("gaps")).toBeInTheDocument();
  expect(scoped.getByLabelText("not available")).toBeInTheDocument();
});

test("the gaps badge is keyboard-focusable and shows its explanation on focus", async () => {
  renderTable();

  const badge = screen.getByText("gaps");
  expect(badge).toHaveAttribute("tabindex", "0");
  act(() => badge.focus());

  expect(
    (await screen.findAllByText(/some recordings lack this metric/i)).length,
  ).toBeGreaterThan(0);
});

test("renders one value column per recording, named from the recordingNames prop", () => {
  renderTable();

  expect(screen.getByRole("columnheader", { name: "Take 1" })).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "Take 2" })).toBeInTheDocument();
});
