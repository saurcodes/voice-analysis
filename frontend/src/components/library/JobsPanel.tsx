import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useDismissJob, useJobs } from "@/api/hooks";
import { JobProgressList, type JobProgressItem } from "./JobProgressList";

const VISIBLE_STATUSES = new Set(["queued", "running", "failed"]);

/**
 * Lists server-side jobs that still need attention (queued/running/failed); hidden
 * entirely when there are none. `excludeIds` lets LibraryPage keep a job started from the
 * currently-open AnalyseDrawer out of this list while that drawer's own JobProgressList is
 * already watching it, so the two don't open a second concurrent SSE connection for the
 * same job.
 *
 * Retry: the backend creates a NEW job and leaves the failed one listed as failed. The
 * failed row is swapped onto the new id in place (its watcher restarts on it) and the new
 * job is kept out of the list as a separate row, so it is watched exactly once. The swap is
 * local to this mount: a later visit lists the old job as failed again, as the server does.
 */
export function JobsPanel({ excludeIds = [] }: { excludeIds?: string[] }) {
  const jobsQuery = useJobs();
  const queryClient = useQueryClient();
  const dismissJob = useDismissJob();
  const [retried, setRetried] = useState<Record<string, string>>({});
  // Dismissed ids are removed from view immediately (optimistic), ahead of the DELETE
  // resolving: a dropped row never has to wait on a round-trip to disappear, and a 404 (the
  // most likely failure, e.g. a double-click) is treated as success anyway.
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const excluded = new Set(excludeIds);
  const retryTargets = new Set(Object.values(retried));
  const jobs = (jobsQuery.data ?? []).filter(
    (job) =>
      VISIBLE_STATUSES.has(job.status) &&
      !excluded.has(job.id) &&
      !retryTargets.has(job.id) &&
      !dismissed.has(job.id),
  );

  if (jobs.length === 0) return null;

  const items: JobProgressItem[] = jobs.map((job) => {
    const retriedAs = retried[job.id];
    return {
      key: job.id,
      fileName: job.file_name ?? "Untitled recording",
      jobId: retriedAs ?? job.id,
      error: !retriedAs && job.status === "failed" ? (job.error ?? "Job failed") : undefined,
    };
  });

  function handleRetried(oldJobId: string, newJobId: string) {
    setRetried((prev) => ({ ...prev, [oldJobId]: newJobId }));
    void queryClient.invalidateQueries({ queryKey: ["vc", "jobs"] });
  }

  function handleDismiss(jobId: string) {
    setDismissed((prev) => new Set(prev).add(jobId));
    dismissJob.mutate(jobId);
  }

  return (
    <section aria-labelledby="jobs-panel-heading" className="mb-6 rounded-lg border border-border bg-card p-4">
      <h2 id="jobs-panel-heading" className="text-sm font-medium text-muted-foreground">
        Processing
      </h2>
      <div className="mt-3">
        <JobProgressList jobs={items} onRetried={handleRetried} onDismiss={handleDismiss} />
      </div>
    </section>
  );
}
