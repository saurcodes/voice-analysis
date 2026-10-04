/**
 * Human labels for job stages, shared between JobsPanel and the AnalyseDrawer's
 * JobProgressList rows. Not every stage event is guaranteed (sse.ts's mapEventToStatus can
 * report "running" with no stage, e.g. after an SSE "timeout" falls back to polling), so an
 * unknown/missing stage falls back to a generic "Working" rather than showing nothing.
 */
const STAGE_LABELS: Record<string, string> = {
  download: "Downloading",
  extract: "Extracting audio",
  analyse: "Analysing voice",
  transcribe: "Transcribing",
  coach: "Coaching",
  done: "Done",
};

export function stageLabel(stage?: string): string {
  if (!stage) return "Working";
  return STAGE_LABELS[stage] ?? "Working";
}
