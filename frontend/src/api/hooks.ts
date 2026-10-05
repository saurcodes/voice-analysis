import { useCallback, useEffect, useMemo } from "react";
import { useLocation } from "react-router";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { useAuthState } from "@/auth/context";
import { ApiError, createApi } from "./client";
import type { components } from "./types";

type CoachRequest = components["schemas"]["CoachRequest"];
type MeResponse = components["schemas"]["MeResponse"];
type PublicConfig = components["schemas"]["PublicConfig"];
type LlmModels = components["schemas"]["LlmModels"];
type AnalysisSummary = components["schemas"]["AnalysisSummary"];
type AnalysisDetail = components["schemas"]["AnalysisDetail"];
type JobStatus = components["schemas"]["JobStatus"];
type JobId = components["schemas"]["JobId"];
type JobIds = components["schemas"]["JobIds"];
type ComparisonResult = components["schemas"]["ComparisonResult"];
type ConnectUrl = components["schemas"]["ConnectUrl"];
type DriveFileOut = components["schemas"]["DriveFileOut"];
export type DriveAnalysisRequest = components["schemas"]["DriveAnalysisRequest"];

const ACTIVE_JOB_STATUSES: ReadonlySet<JobStatus["status"]> = new Set(["queued", "running"]);
const JOBS_REFETCH_MS = 5000;

/**
 * Every API call in the app goes through this: builds client.ts's createApi() from the
 * current auth state, wired so a persistent 401 redirects to Keycloak with the current
 * route (path + search) as returnTo. Memoised on the pieces of AuthState and location that
 * actually change it, so query hooks built on top don't get a new client (and therefore a
 * new queryFn identity) on every render.
 */
export function useApi() {
  const { getToken, signin } = useAuthState();
  const location = useLocation();
  const returnTo = `${location.pathname}${location.search}`;

  const onUnauthorized = useCallback(() => {
    void signin(returnTo);
  }, [signin, returnTo]);

  return useMemo(() => createApi(getToken, onUnauthorized), [getToken, onUnauthorized]);
}

export function useMe() {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "me"] as const,
    queryFn: () => api.get<MeResponse>("/api/me"),
  });
}

export function usePublicConfig() {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "config"] as const,
    queryFn: () => api.get<PublicConfig>("/api/config/public"),
  });
}

const LLM_MODELS_STALE_MS = 5 * 60_000;

/**
 * The provider's model list. Listing hits the LLM server (it can be slow or down), so callers
 * only enable this when they are about to show a model picker; the result stays fresh for five
 * minutes. A server answer (ApiError, e.g. a 503 when the provider is unreachable) is final;
 * only a network-level failure is retried, and just once here (the app-wide default allows
 * two, but a slow/down LLM server isn't worth a third attempt before the caller can react).
 */
export function useLlmModels({ enabled = true }: { enabled?: boolean } = {}) {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "llmModels"] as const,
    queryFn: () => api.get<LlmModels>("/api/llm/models"),
    enabled,
    staleTime: LLM_MODELS_STALE_MS,
    retry: (failureCount, error) => !(error instanceof ApiError) && failureCount < 1,
  });
}

const SUMMARIES_PAGE_SIZE = 50;

/** The Library's main feed: pages of 50 by offset, via useInfiniteQuery rather than
 * useSummaries' growing-limit approach, so "Load more" appends a page instead of re-fetching
 * everything seen so far under a wider limit. A page shorter than the page size is the last
 * one (whether that's because the server ran out of rows, or it was the very first page). */
export function useSummariesInfinite() {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: ["vc", "summaries", "infinite"] as const,
    queryFn: ({ pageParam }) =>
      api.get<AnalysisSummary[]>(`/api/analyses?limit=${SUMMARIES_PAGE_SIZE}&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length < SUMMARIES_PAGE_SIZE ? undefined : allPages.length * SUMMARIES_PAGE_SIZE,
  });
}

export interface JobsParams {
  status?: JobStatus["status"];
}

/** Polls the jobs list every 5s as long as any job in the last response is queued or running. */
export function useJobs({ status }: JobsParams = {}) {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "jobs", { status }] as const,
    queryFn: () => api.get<JobStatus[]>(status ? `/api/jobs?status=${status}` : "/api/jobs"),
    refetchInterval: (query) => {
      const jobs = query.state.data;
      const hasActiveJob = jobs?.some((job) => ACTIVE_JOB_STATUSES.has(job.status)) ?? false;
      return hasActiveJob ? JOBS_REFETCH_MS : false;
    },
  });
}

export function useJob(id: string, { enabled = true }: { enabled?: boolean } = {}) {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "job", id] as const,
    queryFn: () => api.get<JobStatus>(`/api/jobs/${id}`),
    enabled,
  });
}

export function useAnalysis(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "analysis", id] as const,
    queryFn: () => api.get<AnalysisDetail>(`/api/analyses/${id}`),
    enabled: Boolean(id),
  });
}

/** The backend needs at least two ids to compare; a single id (or none) would just get a
 * rejected request, so the query stays disabled until there are 2+. */
export function useComparison(ids: string[]) {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "comparison", ids] as const,
    queryFn: () =>
      api.get<ComparisonResult>(`/api/comparisons?ids=${encodeURIComponent(ids.join(","))}`),
    enabled: ids.length >= 2,
  });
}

const SUMMARIES_KEY: QueryKey = ["vc", "summaries"];
const JOBS_KEY: QueryKey = ["vc", "jobs"];

export function useDeleteAnalysis() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<void>(`/api/analyses/${id}`),
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({ queryKey: SUMMARIES_KEY });
      queryClient.removeQueries({ queryKey: ["vc", "analysis", id] });
    },
  });
}

/** Re-runs coaching for an analysis. On success, writes the updated AnalysisDetail straight
 * into that analysis's query cache (so the Coaching tab re-renders from fresh data without a
 * refetch) and invalidates the summaries list (has_coaching may have flipped). Carries the
 * analysis id in its mutationKey so CoachingPanel's useIsMutating({mutationKey}) can tell
 * whether coaching is running for this specific analysis, independent of any other mutation. */
export function useCoachAnalysis(id: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: ["vc", "coach", id] as const,
    mutationFn: (body: CoachRequest) => api.post<AnalysisDetail>(`/api/analyses/${id}/coach`, body),
    onSuccess: (detail) => {
      queryClient.setQueryData(["vc", "analysis", id], detail);
      void queryClient.invalidateQueries({ queryKey: SUMMARIES_KEY });
    },
  });
}

export function useRetryJob() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<JobId>(`/api/jobs/${id}/retry`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
    },
  });
}

/** Dismisses a terminal (done/failed) job so it drops off JobsPanel. A 404 (already dismissed
 * from another tab, or already gone) is treated as success rather than an error the user has
 * to dismiss a second time. */
export function useDismissJob() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      try {
        await api.del<void>(`/api/jobs/${id}`);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
    },
  });
}

const ME_KEY: QueryKey = ["vc", "me"];

const DRIVE_KEY: QueryKey = ["vc", "drive"];

/** Starts the Drive OAuth flow: fetches the Google consent URL, then navigates the whole
 * page there. The navigation lives in onSuccess (rather than the caller) so it's exercised
 * by the same mutation every caller uses, and is spy-able in tests via window.location.assign.
 * Sent with credentials so the HttpOnly `vc_drive_oauth` state cookie the server sets on this
 * response round-trips back on the callback request (same-origin fetch already carries
 * cookies under the nginx proxy; this call makes that explicit rather than relying on it). */
export function useDriveConnect() {
  const api = useApi();
  return useMutation({
    mutationFn: () => api.get<ConnectUrl>("/api/drive/connect", { credentials: "include" }),
    onSuccess: ({ url }) => {
      window.location.assign(url);
    },
  });
}

/** Disconnecting when the connection is already gone (a 404, e.g. a second click or a stale
 * tab) is treated as success rather than an error the user has to dismiss. Refreshes both
 * /me (drive_connected flips to false) and any cached Drive file listings (so a re-connect
 * doesn't show a stale folder from the previous account). */
export function useDisconnectDrive() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      try {
        await api.del<void>("/api/drive/connect");
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ME_KEY });
      void queryClient.invalidateQueries({ queryKey: DRIVE_KEY });
    },
  });
}

/** Lists Drive files in a folder (root when folderId is empty). A server answer (409 not
 * connected, 503 not configured, 404 folder not found) is final; only a network-level
 * failure is retried, once. Stays fresh for a minute: browsing back into the same folder
 * mid-session shouldn't re-hit Google every time. A 409 (drive_not_connected, e.g. the user
 * revoked access in their Google account since /me last loaded) also refreshes /me so the
 * rest of the app flips to the disconnected state instead of just this one query. */
export function useDriveFiles(folderId: string, { enabled = true }: { enabled?: boolean } = {}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["vc", "drive", "files", folderId] as const,
    queryFn: () =>
      api.get<DriveFileOut[]>(`/api/drive/files?folder_id=${encodeURIComponent(folderId)}`),
    enabled,
    staleTime: 60_000,
    retry: (failureCount, error) => !(error instanceof ApiError) && failureCount < 1,
  });

  useEffect(() => {
    if (query.error instanceof ApiError && query.error.status === 409) {
      void queryClient.invalidateQueries({ queryKey: ME_KEY });
    }
  }, [query.error, queryClient]);

  return query;
}

export function useCreateDriveAnalyses() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: DriveAnalysisRequest) => api.post<JobIds>("/api/analyses", body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
    },
  });
}
