import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useAuthState } from "@/auth/context";
import { authFetch } from "@/api/client";
import { useApi, useRetryJob } from "@/api/hooks";
import { watchJob, type JobStatusLike } from "@/api/sse";
import { stageLabel } from "@/lib/jobs";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * One row's worth of job-progress state as the caller sees it: either a file still
 * uploading (uploadPct, no jobId yet) or a file with a server-side job to watch (jobId).
 * `error` lets a caller seed an already-known failure (e.g. a client-side upload error, or
 * a job the jobs list already reported as failed) without waiting for watchJob's first
 * callback.
 */
export interface JobProgressItem {
  key: string;
  fileName: string;
  jobId?: string;
  uploadPct?: number;
  error?: string;
}

interface LiveStatus {
  status?: string;
  stage?: string;
  progressPct?: number;
  error?: string;
  analysisId?: string | null;
}

/**
 * Renders one row per job/file: a stage label, a progress bar, and the terminal state
 * (an "Open analysis" link on done, or the error + a Retry button on failure). Used by both
 * JobsPanel (server-listed queued/running/failed jobs) and AnalyseDrawer (jobs created by
 * this upload session), so it owns no opinion about where its rows come from.
 */
export function JobProgressList({ jobs }: { jobs: JobProgressItem[] }) {
  const { getToken } = useAuthState();
  const api = useApi();

  const boundAuthFetch = useMemo(
    () => (path: string, init?: RequestInit) => authFetch(path, init, getToken),
    [getToken],
  );
  const getJob = useMemo(() => (id: string) => api.get<JobStatusLike>(`/api/jobs/${id}`), [api]);

  if (jobs.length === 0) return null;

  return (
    <ul className="flex flex-col gap-3">
      {jobs.map((job) => (
        <JobProgressRow key={job.key} job={job} authFetch={boundAuthFetch} getJob={getJob} />
      ))}
    </ul>
  );
}

function JobProgressRow({
  job,
  authFetch: boundAuthFetch,
  getJob,
}: {
  job: JobProgressItem;
  authFetch: (path: string, init?: RequestInit) => Promise<Response>;
  getJob: (id: string) => Promise<JobStatusLike>;
}) {
  const [live, setLive] = useState<LiveStatus>({});
  const retryJob = useRetryJob();
  const reduceMotion = useReducedMotion();
  const jobId = job.jobId;

  useEffect(() => {
    if (!jobId) return;
    const watcher = watchJob(jobId, { authFetch: boundAuthFetch, getJob }, (status) => {
      setLive({
        status: status.status,
        stage: status.stage,
        progressPct: status.progress_pct,
        error: status.error ?? undefined,
        analysisId: status.analysis_id,
      });
    });
    return () => watcher.abort();
  }, [jobId, boundAuthFetch, getJob]);

  const error = live.error ?? job.error;
  const isDone = live.status === "done";
  const isFailed = live.status === "failed" || (!live.status && Boolean(job.error));
  const progressPct = live.progressPct ?? job.uploadPct ?? 0;
  const isUploading = !jobId && !error;

  const label = isDone
    ? stageLabel("done")
    : isFailed
      ? "Failed"
      : isUploading
        ? "Uploading"
        : stageLabel(live.stage);

  return (
    <li className="rounded-lg border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="truncate text-sm font-medium">{job.fileName}</span>
        {isDone ? (
          <span className="flex items-center gap-1 text-sm text-good">
            <CheckCircle weight="regular" className="size-4" />
            Done
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <span>{label}</span>
            {!isFailed && <span className="num">{Math.round(progressPct)}%</span>}
          </span>
        )}
      </div>

      {!isFailed && (
        <div
          role="progressbar"
          aria-valuenow={Math.round(progressPct)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${job.fileName}: ${label}`}
          className="mt-2 h-1.5 w-full overflow-hidden rounded-md bg-muted"
        >
          <motion.div
            className={cn("h-full rounded-md", isDone ? "bg-good" : "bg-primary")}
            animate={{ width: `${Math.round(progressPct)}%` }}
            transition={reduceMotion ? { duration: 0 } : { duration: 0.3, ease: "easeOut" }}
          />
        </div>
      )}

      {isDone && live.analysisId && (
        <Link
          to={`/analyses/${live.analysisId}`}
          className="mt-2 inline-block text-sm font-medium text-primary hover:underline"
        >
          Open analysis
        </Link>
      )}

      {isFailed && (
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 text-sm text-serious">
            <WarningCircle weight="regular" className="size-4 shrink-0" />
            {error ?? "Job failed"}
          </span>
          {jobId && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => retryJob.mutate(jobId)}
              disabled={retryJob.isPending}
            >
              Retry
            </Button>
          )}
        </div>
      )}
    </li>
  );
}
