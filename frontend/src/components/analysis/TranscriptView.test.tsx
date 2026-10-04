import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { analysisDetail } from "@/test/fixtures";
import { TranscriptView } from "./TranscriptView";

/** Matches the element whose full text (visible word plus its sr-only suffix) is exactly
 * `text`, so a flagged word is found by what a screen reader announces. */
function byFullText(text: string) {
  return (_content: string, element: Element | null) => element?.textContent === text;
}

describe("TranscriptView", () => {
  it("shows an empty state when there is no transcript", () => {
    render(<TranscriptView transcript={null} metrics={null} />);
    expect(screen.getByText("No transcript for this recording.")).toBeInTheDocument();
  });

  it("shows an empty state, no legend and no pause chips when the transcript has no words", () => {
    const detail = analysisDetail("default");
    const transcript = { ...detail.transcript!, words: [] };
    render(<TranscriptView transcript={transcript} metrics={detail.metrics} />);

    expect(screen.getByText("No words were recognised in this recording.")).toBeInTheDocument();
    expect(screen.queryByText("Filler word")).not.toBeInTheDocument();
    expect(screen.queryByText(/pause \d/)).not.toBeInTheDocument();
  });

  it("renders a legend whose samples use the same styling as the real markings", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getByText("Pause")).toBeInTheDocument();
    expect(screen.getByText("Eaten word")).toBeInTheDocument();
    expect(screen.getByText("Low confidence")).toBeInTheDocument();
    expect(screen.getByText("Filler word")).toBeInTheDocument();

    const fillerSample = screen.getByText("Filler word").querySelector("[aria-hidden]");
    const fillerWord = screen.getByText(byFullText("so (filler word)"));
    expect(fillerWord.className).toContain("decoration-solid");
    expect(fillerSample?.className).toContain(fillerWord.className);

    const eatenSample = screen.getByText("Eaten word").querySelector("[aria-hidden]");
    const eatenWord = screen.getByText(byFullText("matters (eaten word)"));
    expect(eatenWord.className).toContain("bg-[var(--warning-fill)]/15");
    expect(eatenSample?.className).toContain(eatenWord.className);
  });

  it("marks a filler word with screen-reader text", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    const word = screen.getByText(byFullText("so (filler word)"));
    expect(word).not.toHaveAttribute("aria-label");
    expect(word.querySelector(".sr-only")).toHaveTextContent("(filler word)");
  });

  it("marks an eaten word with screen-reader text", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getByText(byFullText("matters (eaten word)"))).toBeInTheDocument();
  });

  it("marks a word that is both filler and low-confidence with both labels", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getAllByText(byFullText("um (filler word, low confidence)"))).toHaveLength(2);
  });

  it("renders a pause chip with screen-reader text in seconds", () => {
    const detail = analysisDetail("default");
    render(<TranscriptView transcript={detail.transcript} metrics={detail.metrics} />);
    expect(screen.getByText("pause 1.3 seconds")).toHaveClass("sr-only");
    expect(screen.getByText("pause 1.3s")).toHaveAttribute("aria-hidden", "true");
  });
});
