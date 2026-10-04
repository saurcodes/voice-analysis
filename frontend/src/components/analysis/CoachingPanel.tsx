import { useState } from "react";
import { Warning, WarningCircle } from "@phosphor-icons/react";
import { ApiError } from "@/api/client";
import { useCoachAnalysis, useLlmModels, useMe } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

/** Coaching is driven by an opaque JSON blob (the shape lands in Plan 6) plus a flat list
 * of server-side warnings, so field access here stays defensive (string[] lists only
 * rendered when they really are arrays of strings; anything else is skipped rather than
 * crashing on an unexpected shape). */
function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function coachErrorMessage(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === "string") return error.detail;
  return "Something went wrong";
}

/** The warnings list (number/markup post-check misses from the backend) always renders with
 * the shared --warning status colour paired with an icon and text, never colour alone. */
function Checks({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <section>
      <h3 className="text-sm font-medium">Checks</h3>
      <ul className="mt-2 flex flex-col gap-1.5">
        {warnings.map((warning) => (
          <li key={warning} className="flex items-start gap-1.5 text-sm text-warning">
            <Warning weight="regular" className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span>{warning}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RerunCoachingDialog({
  analysisId,
  speakerContext,
  open,
  onOpenChange,
}: {
  analysisId: string;
  speakerContext: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const llmModelsQuery = useLlmModels();
  const coachMutation = useCoachAnalysis();
  // CoachingPanel remounts this component (via `key`) every time the dialog opens, so a
  // lazy initial value here is all "prefilled on open" needs: no effect required to reset it
  // on reopen.
  const [draftContext, setDraftContext] = useState(() => speakerContext ?? "");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const models = llmModelsQuery.data?.models ?? [];
  // Tracks only an explicit user pick; the model actually in effect (below) falls back to
  // the first available one, so the Select preselects it as soon as the list arrives without
  // needing an effect to sync state from the query.
  const [modelOverride, setModelOverride] = useState<string | null>(null);
  const selectedModel = modelOverride && models.includes(modelOverride) ? modelOverride : (models[0] ?? "");

  function handleRun() {
    setSubmitError(null);
    const trimmed = draftContext.trim();
    coachMutation.mutate(
      {
        id: analysisId,
        body: {
          speaker_context: trimmed.length > 0 ? trimmed : null,
          model: selectedModel || null,
        },
      },
      {
        onSuccess: () => onOpenChange(false),
        onError: (error) => setSubmitError(coachErrorMessage(error)),
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Re-run coaching</DialogTitle>
          <DialogDescription>Generate fresh coaching for this analysis.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="coach-speaker-context">Speaker context</Label>
          <Textarea
            id="coach-speaker-context"
            value={draftContext}
            onChange={(event) => setDraftContext(event.target.value)}
            disabled={coachMutation.isPending}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="coach-model">Model</Label>
          <Select
            value={selectedModel}
            onValueChange={setModelOverride}
            disabled={coachMutation.isPending}
          >
            <SelectTrigger id="coach-model" className="w-full">
              <SelectValue placeholder="Choose a model" />
            </SelectTrigger>
            <SelectContent>
              {models.length > 0 ? (
                models.map((model) => (
                  <SelectItem key={model} value={model}>
                    {model}
                  </SelectItem>
                ))
              ) : (
                <SelectItem value="none" disabled>
                  No models available
                </SelectItem>
              )}
            </SelectContent>
          </Select>
        </div>
        {submitError && (
          <p role="alert" className="flex items-center gap-1.5 text-sm text-serious">
            <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
            {submitError}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleRun}
            disabled={coachMutation.isPending || models.length === 0}
          >
            {coachMutation.isPending ? "Running..." : "Run"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function CoachingPanel({
  analysisId,
  coaching,
  coachingWarnings,
  speakerContext,
}: {
  analysisId: string;
  coaching: Record<string, unknown> | null;
  coachingWarnings: unknown[] | null;
  speakerContext: string | null;
}) {
  const meQuery = useMe();
  const [dialogOpen, setDialogOpen] = useState(false);
  // Bumped every time the dialog opens so RerunCoachingDialog is remounted with a fresh key:
  // its draft speaker context, model pick and error state all start clean on each open with
  // plain lazy useState, no effect needed to reset them.
  const [dialogSession, setDialogSession] = useState(0);

  // Stays disabled while /api/me is still loading, not just when it has resolved to false:
  // the button only ever enables once the server has confirmed coaching is on.
  const llmEnabled = meQuery.data?.llm_enabled === true;
  const llmKnownDisabled = meQuery.data?.llm_enabled === false;
  const warnings = stringList(coachingWarnings);

  function openDialog() {
    setDialogSession((session) => session + 1);
    setDialogOpen(true);
  }

  const rerunControls = (
    <div className="flex flex-col items-start gap-1">
      <Button type="button" variant="outline" disabled={!llmEnabled} onClick={openDialog}>
        Re-run coaching
      </Button>
      {llmKnownDisabled && (
        <p className="text-sm text-muted-foreground">Coaching is not enabled on this server yet</p>
      )}
      <RerunCoachingDialog
        key={dialogSession}
        analysisId={analysisId}
        speakerContext={speakerContext}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </div>
  );

  if (!coaching) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-16 text-center">
          <p className="text-sm text-muted-foreground">Coaching is not available yet.</p>
          {warnings.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
        {rerunControls}
      </div>
    );
  }

  const whatImproved = stringList(coaching.what_improved);
  const whatIsLacking = stringList(coaching.what_is_lacking);
  const nextSteps = stringList(coaching.next_steps);
  const markedUpExample = typeof coaching.marked_up_example === "string" ? coaching.marked_up_example : null;

  return (
    <div className="flex flex-col gap-6">
      {whatImproved.length > 0 && (
        <section>
          <h3 className="text-sm font-medium">What improved</h3>
          <ul className="mt-2 list-inside list-disc text-sm text-muted-foreground">
            {whatImproved.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {whatIsLacking.length > 0 && (
        <section>
          <h3 className="text-sm font-medium">What is lacking</h3>
          <ul className="mt-2 list-inside list-disc text-sm text-muted-foreground">
            {whatIsLacking.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {nextSteps.length > 0 && (
        <section>
          <h3 className="text-sm font-medium">Next steps</h3>
          <ul className="mt-2 list-inside list-disc text-sm text-muted-foreground">
            {nextSteps.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {markedUpExample && (
        <section>
          <h3 className="text-sm font-medium">Marked-up example</h3>
          <pre className="num mt-2 whitespace-pre-wrap rounded-lg border border-border bg-muted p-3 text-sm">
            {markedUpExample}
          </pre>
        </section>
      )}
      <Checks warnings={warnings} />
      {rerunControls}
    </div>
  );
}
