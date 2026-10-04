import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { Trash, WarningCircle } from "@phosphor-icons/react";
import { ApiError } from "@/api/client";
import { useAnalysis, useDeleteAnalysis } from "@/api/hooks";
import { AppShell } from "@/components/AppShell";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDateTime, relativeTime } from "@/lib/dates";
import { shortHash } from "@/lib/metrics";
import { CoachingPanel } from "@/components/analysis/CoachingPanel";
import { RawPanel } from "@/components/analysis/RawPanel";
import { SummaryCards } from "@/components/analysis/SummaryCards";
import { TimelineCharts } from "@/components/analysis/TimelineCharts";
import { TranscriptView } from "@/components/analysis/TranscriptView";

const TABS = ["summary", "timeline", "transcript", "coaching", "raw"] as const;
type TabValue = (typeof TABS)[number];

function isTabValue(value: string | null): value is TabValue {
  return (TABS as readonly string[]).includes(value ?? "");
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === "string") return error.detail;
  return "Something went wrong. Try again.";
}

function HeaderSkeleton() {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex flex-col gap-2">
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-4 w-40" />
      </div>
      <Skeleton className="h-9 w-24" />
    </div>
  );
}

function CardsSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 8 }, (_, i) => (
        <Skeleton key={i} className="h-28 w-full" />
      ))}
    </div>
  );
}

export function AnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const analysisQuery = useAnalysis(id ?? "");
  const deleteAnalysis = useDeleteAnalysis();

  const tabParam = searchParams.get("tab");
  const activeTab: TabValue = isTabValue(tabParam) ? tabParam : "summary";

  function setActiveTab(next: string) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  function confirmDelete() {
    if (!id) return;
    setDeleteError(null);
    deleteAnalysis.mutate(id, {
      onSuccess: () => navigate("/"),
      onError: (error) => setDeleteError(errorDetail(error)),
    });
  }

  if (analysisQuery.isLoading) {
    return (
      <AppShell>
        <div className="flex flex-col gap-6">
          <HeaderSkeleton />
          <CardsSkeleton />
        </div>
      </AppShell>
    );
  }

  if (analysisQuery.isError) {
    const error = analysisQuery.error;
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <AppShell>
        <div className="flex flex-col items-center gap-3 rounded-lg border border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">
            {notFound ? "This analysis was not found." : errorDetail(error)}
          </p>
          <Button type="button" variant="outline" asChild>
            <Link to="/">Back to Library</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  const analysis = analysisQuery.data;
  if (!analysis) return null;

  return (
    <AppShell>
      <div className="flex flex-col gap-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-xl font-semibold tracking-tight">{analysis.file_name}</h1>
            <p className="text-sm text-muted-foreground">
              Recorded {formatDateTime(analysis.recorded_at)} ({relativeTime(analysis.recorded_at)})
            </p>
            <p className="num text-xs text-muted-foreground">
              {analysis.analyser_version} / {shortHash(analysis.config_hash)}
            </p>
          </div>
          <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
            <Trash weight="regular" />
            Delete
          </Button>
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="summary">Summary</TabsTrigger>
            <TabsTrigger value="timeline">Timeline</TabsTrigger>
            <TabsTrigger value="transcript">Transcript</TabsTrigger>
            <TabsTrigger value="coaching">Coaching</TabsTrigger>
            <TabsTrigger value="raw">Raw</TabsTrigger>
          </TabsList>

          <TabsContent value="summary" className="pt-6">
            <SummaryCards metrics={analysis.metrics} transcript={analysis.transcript} />
          </TabsContent>

          <TabsContent value="timeline" className="pt-6">
            <TimelineCharts metrics={analysis.metrics} />
          </TabsContent>

          <TabsContent value="transcript" className="pt-6">
            <TranscriptView transcript={analysis.transcript} metrics={analysis.metrics} />
          </TabsContent>

          <TabsContent value="coaching" className="pt-6">
            <CoachingPanel
              analysisId={analysis.id}
              coaching={analysis.coaching}
              coachingWarnings={analysis.coaching_warnings}
              speakerContext={analysis.speaker_context}
            />
          </TabsContent>

          <TabsContent value="raw" className="pt-6">
            <RawPanel
              analysisId={analysis.id}
              hasTranscript={analysis.transcript !== null}
              hasCoaching={analysis.coaching !== null}
            />
          </TabsContent>
        </Tabs>
      </div>

      <Dialog open={confirmOpen} onOpenChange={(open) => { setConfirmOpen(open); if (!open) setDeleteError(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this analysis?</DialogTitle>
            <DialogDescription>This cannot be undone.</DialogDescription>
          </DialogHeader>
          {deleteError && (
            <p role="alert" className="flex items-center gap-1.5 text-sm text-serious">
              <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
              {deleteError}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={confirmDelete}
              disabled={deleteAnalysis.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
