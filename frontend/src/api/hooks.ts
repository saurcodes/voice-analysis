import { useCallback, useMemo } from "react";
import { useLocation } from "react-router";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { useAuthState } from "@/auth/context";
import { createApi } from "./client";
import type { components } from "./types";

type MeResponse = components["schemas"]["MeResponse"];
type PublicConfig = components["schemas"]["PublicConfig"];
type LlmModels = components["schemas"]["LlmModels"];
type AnalysisSummary = components["schemas"]["AnalysisSummary"];
type AnalysisDetail = components["schemas"]["AnalysisDetail"];
type JobStatus = components["schemas"]["JobStatus"];
type JobId = components["schemas"]["JobId"];
type ComparisonResult = components["schemas"]["ComparisonResult"];

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

export function useLlmModels() {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "llmModels"] as const,
    queryFn: () => api.get<LlmModels>("/api/llm/models"),
  });
}

export interface SummariesParams {
  limit?: number;
  offset?: number;
}

export function useSummaries({ limit = 50, offset = 0 }: SummariesParams = {}) {
  const api = useApi();
  return useQuery({
    queryKey: ["vc", "summaries", { limit, offset }] as const,
    queryFn: () =>
      api.get<AnalysisSummary[]>(`/api/analyses?limit=${limit}&offset=${offset}`),
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
