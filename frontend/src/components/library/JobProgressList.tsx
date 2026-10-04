import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { motion, useReducedMotion } from "motion/react";
import { useAuthState } from "@/auth/context";
import { ApiError, authFetch } from "@/api/client";
import { useApi, useRetryJob } from "@/api/hooks";
import { watchJob, type JobStatusLike } from "@/api/sse";
import { stageLabel } from "@/lib/jobs";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * One row's worth of job-progress state as the caller sees it: a file waiting its turn in
 * a batch (no uploadPct, no jobId), a file still uploading (uploadPct, no jobId yet), or a
 * file with a server-side job to watch (jobId). `error` lets a caller seed an already-known
 * failure (e.g. a client-side upload error, or a job the jobs list already reported as
 * failed) without waiting for a watcher; a row seeded as failed is not watched at all.
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

type AuthFetch = (path: string, init?: RequestInit) => Promise<Response>;
type GetJob = (id: string) => Promise<JobStatusLike>;

const TERMINAL_STATUSES = new Set(["done", "failed"]);

/** Only the fields a status actually carries, so merging it never blanks out earlier ones
 * (a poll or progress frame with no stage must not erase the stage label already shown). */
function definedFields(status: JobStatusLike): LiveStatus {
  const next: LiveStatus = { status: status.status };
  if (status.stage !== undefined) next.stage = status.stage;
  if (status.progress_pct !== undefined) next.progressPct = status.progress_pct;
  if (status.error) next.error = status.error;
  if (status.analysis_id !== undefined) next.analysisId = status.analysis_id;
  return next;
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === "string" ? error.detail : error.message;
  }
  return error instanceof Error ? error.message : "Retry failed";
}

/**
 * Renders one row per job/file: a stage label, a progress bar, and the terminal state
 * (an "Open analysis" link on done, or the error + a Retry button on failure). Used by both
 * JobsPanel (server-listed queued/running/failed jobs) and AnalyseDrawer (jobs created by
 * this upload session), so it owns no opinion about where its rows come from. A successful
 * retry swaps the row onto the new job id (the watcher restarts on it) and reports the pair
 * through onRetried so the owner can stop listing the new job a second time.
 */
export function JobProgressList({
  jobs,
  onRetried,
}: {
  jobs: JobProgressItem[];
  onRetried?: (oldJobId: string, newJobId: string) => void;
}) {
  const { getToken } = useAuthState();
  const api = useApi();
  const queryClient = useQueryClient();

  const boundAuthFetch = useMemo<AuthFetch>(
    () => (path, init) => authFetch(path, init, getToken),
    [getToken],
  );
  const getJob = useMemo<GetJob>(() => (id) => api.get<JobStatusLike>(`/api/jobs/${id}`), [api]);

  if (jobs.length === 0) return null;

  return (
    <ul className="flex flex-col gap-3">
      {jobs.map((job) => (
        <JobProgressRow
          key={job.key}
          job={job}
          authFetch={boundAuthFetch}
          getJob={getJob}
          queryClient={queryClient}
          onRetried={onRetried}
        />
      ))}
    </ul>
  );
}

function JobProgressRow({
  job,
  authFetch: boundAuthFetch,
  getJob,
  queryClient,
  onRetried,
}: {
  job: JobProgressItem;
  authFetch: AuthFetch;
  getJob: GetJob;
  queryClient: QueryClient;
  onRetried?: (oldJobId: string, newJobId: string) => void;
}) {
  const [live, setLive] = useState<LiveStatus>({});
  const [retriedJobId, setRetriedJobId] = useState<string | undefined>();
  const [retryError, setRetryError] = useState<string | undefined>();
  const retryJob = useRetryJob();
  const reduceMotion = useReducedMotion();

  const jobId = retriedJobId ?? job.jobId;
  // A retry replaces whatever failure the caller seeded: the new job starts clean.
  const seededError = retriedJobId ? undefined : job.error;
  const watchId = seededError ? undefined : jobId;

  // The watcher reads its collaborators through a ref so it only restarts when the job id
  // changes, not every time auth state or the route hands down new function identities.
  const depsRef = useRef({ authFetch: boundAuthFetch, getJob, queryClient });
  useLayoutEffect(() => {
    depsRef.current = { authFetch: boundAuthFetch, getJob, queryClient };
  });

  useEffect(() => {
    if (!watchId) return;
    const watcher = watchJob(
      watchId,
      {
        authFetch: (path, init) => depsRef.current.authFetch(path, init),
        getJob: (id) => depsRef.current.getJob(id),
      },
      (status) => {
        setLive((prev) => ({ ...prev, ...definedFields(status) }));
        if (TERMINAL_STATUSES.has(status.status)) {
          const client = depsRef.current.queryClient;
          void client.invalidateQueries({ queryKey: ["vc", "summaries"] });
          void client.invalidateQueries({ queryKey: ["vc", "jobs"] });
        }
      },
    );
    return () => watcher.abort();
  }, [watchId]);

  function handleRetry() {
    if (!jobId) return;
    const oldJobId = jobId;
    setRetryError(undefined);
    retryJob.mutate(oldJobId, {
      onSuccess: ({ job_id: newJobId }) => {
        setLive({});
        setRetriedJobId(newJobId);
        onRetried?.(oldJobId, newJobId);
      },
      onError: (error) => setRetryError(errorDetail(error)),
    });
  }

  const error = live.error ?? seededError;
  const isDone = live.status === "done";
  const isFailed = live.status === "failed" || (!live.status && Boolean(seededError));
  const isWaiting = !jobId && !seededError && job.uploadPct === undefined;
  const isUploading = !jobId && !seededError && job.uploadPct !== undefined;
  const progressPct = isDone ? 100 : (live.progressPct ?? job.uploadPct ?? 0);

  const label = isDone
    ? stageLabel("done")
    : isFailed
      ? "Failed"
      : isWaiting
        ? "Waiting"
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
            {!isFailed && !isWaiting && <span className="num">{Math.round(progressPct)}%</span>}
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
            className={cn("h-full rounded-md", isDone ? "bg-good-fill" : "bg-primary")}
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
        <div className="mt-2 flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-sm text-serious">
              <WarningCircle weight="regular" className="size-4 shrink-0" />
              {error ?? "Job failed"}
            </span>
            {jobId && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleRetry}
                disabled={retryJob.isPending}
              >
                Retry
              </Button>
            )}
          </div>
          {retryError && (
            <p role="alert" className="flex items-center gap-1.5 text-sm text-serious">
              <WarningCircle weight="regular" className="size-4 shrink-0" />
              Retry failed: {retryError}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
