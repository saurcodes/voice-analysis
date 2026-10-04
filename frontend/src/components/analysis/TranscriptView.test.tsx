import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { analysisDetail } from "@/test/fixtures";
import { TranscriptView } from "./TranscriptView";

describe("TranscriptView", () => {
  it("shows an empty state when there is no transcript", () => {
    render(<TranscriptView transcript={null} metrics={null} />);
    expect(screen.getByText("No transcript for this recording.")).toBeInTheDocument();
  });

  it("renders the legend row", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getByText("Pause")).toBeInTheDocument();
    expect(screen.getByText("Eaten word")).toBeInTheDocument();
    expect(screen.getByText("Low confidence")).toBeInTheDocument();
    expect(screen.getByText("Filler word")).toBeInTheDocument();
  });

  it("marks a filler word with an accessible label", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getByLabelText("filler word: so")).toBeInTheDocument();
  });

  it("marks an eaten word with an accessible label", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getByLabelText("eaten word: matters")).toBeInTheDocument();
  });

  it("marks a word that is both filler and low-confidence with both labels", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getAllByLabelText("filler word: um, low confidence: um")).toHaveLength(2);
  });

  it("renders a pause chip with an accessible label", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getByLabelText("pause 1.3 seconds")).toBeInTheDocument();
  });
});
