import { useState } from "react";
import { Link } from "react-router";
import { ArrowSquareOut, Trash, WarningCircle } from "@phosphor-icons/react";
import { ApiError } from "@/api/client";
import { useDeleteAnalysis, useSummariesInfinite } from "@/api/hooks";
import type { components } from "@/api/types";
import { formatDateTime, relativeTime } from "@/lib/dates";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { EmptyLibrary } from "./EmptyLibrary";

type AnalysisSummary = components["schemas"]["AnalysisSummary"];

const COLUMNS = [
  "Select",
  "File",
  "Recorded",
  "Pitch range (st)",
  "Flat endings %",
  "Pauses/min",
  "Fillers/min",
  "Transcript",
  "Coaching",
  "Actions",
] as const;

function MetricCell({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <span className="num text-muted-foreground" aria-label="not available">
        -
      </span>
    );
  }
  return <span className="num">{value.toFixed(1)}</span>;
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === "string" ? error.detail : error.message;
  }
  return "Something went wrong. Try again.";
}

export function AnalysesTable({
  selectedIds,
  onToggleSelected,
  onAnalyseClick,
  onDeleted,
}: {
  selectedIds: string[];
  onToggleSelected: (id: string) => void;
  onAnalyseClick: () => void;
  /** Called after a delete succeeds, so the page can drop the id from its own selection
   * state (otherwise a deleted row's id would linger in selectedIds and Compare could
   * navigate with a dead id). */
  onDeleted?: (id: string) => void;
}) {
  const summariesQuery = useSummariesInfinite();
  const [confirmTarget, setConfirmTarget] = useState<AnalysisSummary | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteAnalysis = useDeleteAnalysis();

  const selected = new Set(selectedIds);
  const rows = summariesQuery.data?.pages.flat() ?? [];
  const hasMore = summariesQuery.hasNextPage ?? false;

  function closeDialog() {
    setConfirmTarget(null);
    setDeleteError(null);
  }

  function confirmDelete() {
    if (!confirmTarget) return;
    const id = confirmTarget.id;
    setDeleteError(null);
    deleteAnalysis.mutate(id, {
      onSuccess: () => {
        closeDialog();
        onDeleted?.(id);
      },
      onError: (error) => setDeleteError(errorDetail(error)),
    });
  }

  if (summariesQuery.isLoading) {
    return (
      <Table>
        <TableHeader>
          <TableRow>
            {COLUMNS.map((column) => (
              <TableHead key={column}>{column}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: 5 }, (_, i) => (
            <TableRow key={i}>
              {COLUMNS.map((column) => (
                <TableCell key={column}>
                  <Skeleton className="h-4 w-full max-w-24" />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }

  if (summariesQuery.isError) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-lg border border-border py-16 text-center">
        <WarningCircle weight="regular" className="size-6 text-serious" />
        <p className="text-sm text-muted-foreground">
          {errorDetail(summariesQuery.error)}
        </p>
        <Button type="button" variant="outline" size="sm" onClick={() => void summariesQuery.refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (rows.length === 0) {
    return <EmptyLibrary onAnalyse={onAnalyseClick} />;
  }

  return (
    <TooltipProvider>
      <Table>
        <TableHeader>
          <TableRow>
            {COLUMNS.map((column) => (
              <TableHead key={column} className={column === "Select" ? "w-8" : undefined}>
                {column === "Select" ? <span className="sr-only">Select</span> : column}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id} data-state={selected.has(row.id) ? "selected" : undefined}>
              <TableCell>
                <Checkbox
                  checked={selected.has(row.id)}
                  onCheckedChange={() => onToggleSelected(row.id)}
                  aria-label={`Select ${row.file_name}`}
                />
              </TableCell>
              <TableCell className="max-w-48 truncate font-medium">{row.file_name}</TableCell>
              <TableCell>
                <Tooltip>
                  <TooltipTrigger asChild>
                    {/* Focusable so keyboard users reach the exact date too, not just hover. */}
                    <span
                      tabIndex={0}
                      className="num cursor-default rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      {relativeTime(row.recorded_at)}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>{formatDateTime(row.recorded_at)}</TooltipContent>
                </Tooltip>
              </TableCell>
              <TableCell>
                <MetricCell value={row.f0_range_st} />
              </TableCell>
              <TableCell>
                <MetricCell value={row.flat_pct} />
              </TableCell>
              <TableCell>
                <MetricCell value={row.pauses_per_min} />
              </TableCell>
              <TableCell>
                <MetricCell value={row.fillers_per_min} />
              </TableCell>
              <TableCell>
                <Badge variant="outline">{row.has_transcript ? "Yes" : "No"}</Badge>
              </TableCell>
              <TableCell>
                <Badge variant="outline">{row.has_coaching ? "Yes" : "No"}</Badge>
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="icon-sm" asChild>
                    <Link to={`/analyses/${row.id}`} aria-label={`Open ${row.file_name}`}>
                      <ArrowSquareOut weight="regular" />
                    </Link>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Delete ${row.file_name}`}
                    onClick={() => setConfirmTarget(row)}
                  >
                    <Trash weight="regular" />
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      {hasMore && (
        <div className="mt-4 flex justify-center">
          <Button
            type="button"
            variant="outline"
            onClick={() => void summariesQuery.fetchNextPage()}
            disabled={summariesQuery.isFetchingNextPage}
          >
            {summariesQuery.isFetchingNextPage ? "Loading..." : "Load more"}
          </Button>
        </div>
      )}

      <Dialog open={Boolean(confirmTarget)} onOpenChange={(open) => !open && closeDialog()}>
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
            <Button type="button" variant="outline" onClick={closeDialog}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={confirmDelete} disabled={deleteAnalysis.isPending}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}
