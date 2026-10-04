import { useState } from "react";
import { Download, WarningCircle } from "@phosphor-icons/react";
import { useAuthState } from "@/auth/context";
import { ApiError, authFetch } from "@/api/client";
import { Button } from "@/components/ui/button";

type RawKind = "metrics" | "transcript" | "coaching";

interface RawRow {
  kind: RawKind;
  label: string;
  available: boolean;
}

/** RFC 6266 allows both `filename=` (legacy, ASCII) and `filename*=` (RFC 5987, UTF-8 +
 * percent-encoded) on the same header, with `filename=` conventionally listed first for
 * backward compatibility. `filename*=` is checked first so its properly-encoded value
 * wins whenever both are present. */
function parseFilename(contentDisposition: string | null, fallback: string): string {
  if (!contentDisposition) return fallback;
  const extended = /filename\*=(?:UTF-8'')?([^";]+)/i.exec(contentDisposition);
  if (extended) return decodeURIComponent(extended[1]);
  const plain = /filename="?([^";]+)"?/i.exec(contentDisposition);
  return plain ? decodeURIComponent(plain[1]) : fallback;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    // fall through to the generic message below
  }
  return "Download failed.";
}

/** Metrics / Transcript / Coaching download rows. Each button fetches the raw JSON via
 * authFetch (so it carries the bearer token and a silent-renew retry the same way every
 * other API call does), then triggers a browser download through a throwaway object URL. */
export function RawPanel({
  analysisId,
  hasTranscript,
  hasCoaching,
}: {
  analysisId: string;
  hasTranscript: boolean;
  hasCoaching: boolean;
}) {
  const { getToken } = useAuthState();
  const [errors, setErrors] = useState<Partial<Record<RawKind, string>>>({});
  const [pending, setPending] = useState<RawKind | null>(null);

  const rows: RawRow[] = [
    { kind: "metrics", label: "Metrics", available: true },
    { kind: "transcript", label: "Transcript", available: hasTranscript },
    { kind: "coaching", label: "Coaching", available: hasCoaching },
  ];

  async function download(kind: RawKind) {
    setErrors((prev) => ({ ...prev, [kind]: undefined }));
    setPending(kind);
    try {
      const response = await authFetch(`/api/analyses/${analysisId}/raw/${kind}`, undefined, getToken);
      if (!response.ok) {
        throw new ApiError(response.status, await errorDetail(response));
      }
      const blob = await response.blob();
      const filename = parseFilename(response.headers.get("Content-Disposition"), `${kind}.json`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      // Revoking synchronously can cancel the download in some browsers before it starts.
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      const message = error instanceof ApiError ? String(error.detail) : "Download failed.";
      setErrors((prev) => ({ ...prev, [kind]: message }));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex flex-col divide-y divide-border border-y border-border">
      {rows.map((row) => (
        <div key={row.kind} className="flex flex-col gap-1 py-4">
          <div className="flex items-center justify-between gap-4">
            <span className="text-sm font-medium">{row.label}</span>
            {row.available ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={pending === row.kind}
                onClick={() => void download(row.kind)}
              >
                <Download weight="regular" />
                Download
              </Button>
            ) : (
              <span className="text-sm text-muted-foreground">Not available</span>
            )}
          </div>
          {errors[row.kind] && (
            <p role="alert" className="flex items-center gap-1.5 text-sm text-serious">
              <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
              {errors[row.kind]}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
