import { useMe } from "@/api/hooks";
import { Button } from "@/components/ui/button";

/** Coaching is driven by an opaque JSON blob (the shape lands in Plan 6) plus a flat list
 * of server-side warnings, so field access here stays defensive (string[] lists only
 * rendered when they really are arrays of strings; anything else is skipped rather than
 * crashing on an unexpected shape). */
function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

export function CoachingPanel({
  coaching,
  coachingWarnings,
}: {
  coaching: Record<string, unknown> | null;
  coachingWarnings: unknown[] | null;
}) {
  const meQuery = useMe();
  const llmDisabled = meQuery.data?.llm_enabled === false;

  if (!coaching) {
    const warnings = stringList(coachingWarnings);
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
        <div className="flex flex-col items-start gap-1">
          <Button type="button" variant="outline" disabled>
            Re-run coaching
          </Button>
          {llmDisabled && (
            <p className="text-sm text-muted-foreground">Coaching is not enabled on this server yet</p>
          )}
        </div>
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
      <div className="flex flex-col items-start gap-1">
        <Button type="button" variant="outline" disabled>
          Re-run coaching
        </Button>
        {llmDisabled && (
          <p className="text-sm text-muted-foreground">Coaching is not enabled on this server yet</p>
        )}
      </div>
    </div>
  );
}
