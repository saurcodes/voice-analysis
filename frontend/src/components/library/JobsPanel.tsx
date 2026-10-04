import { useJobs } from "@/api/hooks";
import { JobProgressList, type JobProgressItem } from "./JobProgressList";

const VISIBLE_STATUSES = new Set(["queued", "running", "failed"]);

/**
 * Lists server-side jobs that still need attention (queued/running/failed); hidden
 * entirely when there are none. `excludeIds` lets LibraryPage keep a job started from the
 * currently-open AnalyseDrawer out of this list while that drawer's own JobProgressList is
 * already watching it, so the two don't open a second concurrent SSE connection for the
 * same job. LibraryPage clears that exclusion (and this panel's jobs query gets
 * invalidated) once the drawer closes.
 */
export function JobsPanel({ excludeIds = [] }: { excludeIds?: string[] }) {
  const jobsQuery = useJobs();
  const excluded = new Set(excludeIds);
  const jobs = (jobsQuery.data ?? []).filter(
    (job) => VISIBLE_STATUSES.has(job.status) && !excluded.has(job.id),
  );

  if (jobs.length === 0) return null;

  const items: JobProgressItem[] = jobs.map((job) => ({
    key: job.id,
    fileName: job.file_name ?? "Untitled recording",
    jobId: job.id,
    error: job.status === "failed" ? (job.error ?? "Job failed") : undefined,
  }));

  return (
    <section aria-labelledby="jobs-panel-heading" className="mb-6 rounded-lg border border-border bg-card p-4">
      <h2 id="jobs-panel-heading" className="text-sm font-medium text-muted-foreground">
        Processing
      </h2>
      <div className="mt-3">
        <JobProgressList jobs={items} />
      </div>
    </section>
  );
}
