import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthState } from "@/auth/context";
import { ApiError } from "@/api/client";
import { useLlmModels, useMe } from "@/api/hooks";
import { uploadAnalysis } from "@/api/upload";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { JobProgressList, type JobProgressItem } from "./JobProgressList";
import { UploadDropzone } from "./UploadDropzone";

function rowKey(batch: number, file: File, index: number): string {
  return `${batch}-${file.name}-${file.lastModified}-${index}`;
}

function errorDetail(error: unknown): string {
  if (error instanceof ApiError) {
    return typeof error.detail === "string" ? error.detail : error.message;
  }
  return "Upload failed";
}

export interface AnalyseDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Reported once per file whose upload created a server-side job, so LibraryPage can keep
   * JobsPanel from double-watching a job this drawer's own JobProgressList already owns. */
  onJobsCreated?: (jobIds: string[]) => void;
}

/**
 * The "Analyse" side panel: pick files (upload tab; Drive is a disabled placeholder until
 * Plan 7), add speaker context, optionally enable coaching, then upload sequentially. Each
 * file becomes a JobProgressList row that starts as an upload-progress bar and, once the
 * server returns a job id, switches to live job-stage progress.
 */
export function AnalyseDrawer({ open, onOpenChange, onJobsCreated }: AnalyseDrawerProps) {
  const { getToken } = useAuthState();
  const queryClient = useQueryClient();
  const meQuery = useMe();
  const llmModelsQuery = useLlmModels();

  const [files, setFiles] = useState<File[]>([]);
  const [speakerContext, setSpeakerContext] = useState("");
  const [llmEnabled, setLlmEnabled] = useState(false);
  // Tracks only an explicit user pick; the actual selected model (below) falls back to the
  // first available model so the Select preselects one as soon as the list arrives, without
  // an effect to sync it (this project's lint config flags setState calls made from effects).
  const [llmModelOverride, setLlmModelOverride] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [rows, setRows] = useState<JobProgressItem[]>([]);
  const batchRef = useRef(0);

  const llmDisabled = meQuery.data?.llm_enabled === false;
  const llmModels = llmModelsQuery.data?.models ?? [];
  const llmModel =
    llmModelOverride && llmModels.includes(llmModelOverride) ? llmModelOverride : (llmModels[0] ?? "");

  function resetForm() {
    setFiles([]);
    setSpeakerContext("");
    setLlmEnabled(false);
    setLlmModelOverride(null);
    setRows([]);
  }

  function handleOpenChange(next: boolean) {
    // Closing mid-batch would drop the remaining uploads on the floor: the drawer stays
    // open (Escape, outside click and the Close button are all blocked) until they finish.
    if (!next && submitting) return;
    if (!next) {
      void queryClient.invalidateQueries({ queryKey: ["vc", "jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["vc", "summaries"] });
      resetForm();
    }
    onOpenChange(next);
  }

  async function handleSubmit() {
    if (files.length === 0 || submitting) return;
    setSubmitting(true);
    batchRef.current += 1;
    const batch = batchRef.current;

    // Rows for this batch start as "Waiting" (no uploadPct) and are appended, so rows from an
    // earlier batch in the same drawer session keep their watchers.
    const batchRows: JobProgressItem[] = files.map((file, index) => ({
      key: rowKey(batch, file, index),
      fileName: file.name,
    }));
    setRows((prev) => [...prev, ...batchRows]);

    for (let index = 0; index < files.length; index++) {
      const file = files[index];
      const key = rowKey(batch, file, index);
      setRows((prev) => prev.map((row) => (row.key === key ? { ...row, uploadPct: 0 } : row)));
      try {
        const result = await uploadAnalysis(
          file,
          {
            speaker_context: speakerContext.trim() || undefined,
            llm_enabled: llmEnabled && !llmDisabled,
            llm_model: llmEnabled && !llmDisabled && llmModel ? llmModel : undefined,
          },
          {
            getToken,
            onProgress: (pct) => {
              setRows((prev) => prev.map((row) => (row.key === key ? { ...row, uploadPct: pct } : row)));
            },
          },
        );
        const jobId = result.job_ids[0];
        setRows((prev) =>
          prev.map((row) => (row.key === key ? { ...row, jobId, uploadPct: undefined } : row)),
        );
        // Report each job as soon as it exists (not once after the loop), so the Library's
        // JobsPanel never double-watches it and picks it up if the drawer is later closed.
        if (jobId) {
          onJobsCreated?.([jobId]);
          void queryClient.invalidateQueries({ queryKey: ["vc", "jobs"] });
        }
      } catch (error) {
        const message = errorDetail(error);
        setRows((prev) => prev.map((row) => (row.key === key ? { ...row, error: message } : row)));
      }
    }

    setSubmitting(false);
    // The batch is out of the picker: clear it so the button reads "Analyse 0 files" again.
    // The progress rows stay.
    setFiles([]);
  }

  function handleRetried(_oldJobId: string, newJobId: string) {
    onJobsCreated?.([newJobId]);
  }

  const submitLabel = `Analyse ${files.length} file${files.length === 1 ? "" : "s"}`;

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col sm:max-w-xl"
        closeDisabled={submitting}
        onInteractOutside={(event) => {
          if (submitting) event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          if (submitting) event.preventDefault();
        }}
      >
        <SheetHeader>
          <SheetTitle>Analyse recordings</SheetTitle>
          <SheetDescription>Upload one or more recordings to analyse.</SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-6 overflow-y-auto px-4 pb-4">
          <Tabs defaultValue="upload">
            <TabsList>
              <TabsTrigger value="upload">Upload</TabsTrigger>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="flex-1">
                      <TabsTrigger
                        value="drive"
                        disabled
                        aria-describedby="drive-tab-note"
                        className="pointer-events-none w-full"
                      >
                        Google Drive
                      </TabsTrigger>
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>Available in a later release</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </TabsList>
            {/* Tooltip content only reaches pointer users; a disabled button gets no hover
                from assistive tech or keyboard focus, so the same explanation is also a
                plain visible line the disabled trigger's aria-describedby points at. */}
            <p id="drive-tab-note" className="text-xs text-muted-foreground">
              Google Drive import is available in a later release
            </p>
            <TabsContent value="upload">
              <UploadDropzone files={files} onFilesChange={setFiles} disabled={submitting} />
            </TabsContent>
            <TabsContent value="drive" />
          </Tabs>

          <div className="flex flex-col gap-2">
            <Label htmlFor="speaker-context">Speaker context</Label>
            <Textarea
              id="speaker-context"
              value={speakerContext}
              onChange={(event) => setSpeakerContext(event.target.value)}
              placeholder="e.g. real estate sales pitch"
              disabled={submitting}
            />
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="llm-switch">Coaching</Label>
              <Switch
                id="llm-switch"
                checked={llmEnabled}
                onCheckedChange={setLlmEnabled}
                disabled={llmDisabled || submitting}
              />
            </div>
            {llmDisabled ? (
              <p className="text-sm text-muted-foreground">Coaching is not enabled on this server yet</p>
            ) : (
              llmEnabled && (
                <Select value={llmModel} onValueChange={setLlmModelOverride}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Choose a model" />
                  </SelectTrigger>
                  <SelectContent>
                    {llmModels.map((model) => (
                      <SelectItem key={model} value={model}>
                        {model}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )
            )}
          </div>

          {rows.length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">Progress</h3>
              <JobProgressList jobs={rows} onRetried={handleRetried} />
            </div>
          )}
        </div>

        <SheetFooter>
          {submitting && (
            <p role="status" className="text-sm text-muted-foreground">
              Uploads in progress
            </p>
          )}
          <Button type="button" onClick={() => void handleSubmit()} disabled={files.length === 0 || submitting}>
            {submitLabel}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
