import { ApiError, detailFromBody } from "./client";
import type { components } from "./types";

/**
 * POST /api/analyses is multipart/form-data, so it can't go through client.ts's postForm()
 * if callers want upload progress: XMLHttpRequest is the only thing in the browser that
 * exposes upload.onprogress. This is the one place in the app that reaches for XHR instead
 * of fetch for that reason alone.
 */

export interface UploadFields {
  speaker_context?: string;
  llm_enabled?: boolean;
  llm_model?: string;
  recorded_at?: string;
}

export interface UploadOptions {
  getToken: () => Promise<string>;
  onProgress?: (pct: number) => void;
  /** Lets a caller cancel an in-flight upload (e.g. a per-row Cancel button). Aborting the
   * underlying XHR rejects with ApiError(0, "upload cancelled") rather than the generic
   * "Network error" an onerror would produce, so callers can tell a cancel apart from a real
   * network failure. */
  signal?: AbortSignal;
}

export type UploadResult = components["schemas"]["JobIds"];

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function buildForm(file: File, fields: UploadFields): FormData {
  const form = new FormData();
  form.append("file", file);
  if (fields.speaker_context !== undefined) form.append("speaker_context", fields.speaker_context);
  if (fields.llm_enabled !== undefined) form.append("llm_enabled", String(fields.llm_enabled));
  if (fields.llm_model !== undefined) form.append("llm_model", fields.llm_model);
  const recordedAt = fields.recorded_at ?? new Date(file.lastModified).toISOString();
  form.append("recorded_at", recordedAt);
  return form;
}

/**
 * Uploads a recording with progress reporting. Maps a non-2xx response to ApiError using
 * the same {detail} / FastAPI 422-list rule as client.ts (via the shared detailFromBody()),
 * so a 413/415/422 from this endpoint renders identically to any other API error.
 * recorded_at defaults to the file's own lastModified timestamp when the caller doesn't
 * supply one, so an upload from a file picker carries a sensible recording time out of the
 * box.
 */
export function uploadAnalysis(
  file: File,
  fields: UploadFields,
  { getToken, onProgress, signal }: UploadOptions,
): Promise<UploadResult> {
  if (signal?.aborted) {
    return Promise.reject(new ApiError(0, "upload cancelled"));
  }

  return getToken().then(
    (token) =>
      new Promise<UploadResult>((resolve, reject) => {
        const form = buildForm(file, fields);
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/analyses");
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);

        xhr.upload.onprogress = (event) => {
          if (!onProgress || !event.lengthComputable || event.total === 0) return;
          onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
        };

        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            const body = parseJson(xhr.responseText);
            if (body === undefined) {
              reject(new ApiError(xhr.status, "Malformed response"));
              return;
            }
            resolve(body as UploadResult);
            return;
          }
          const body = parseJson(xhr.responseText);
          const detail = body === undefined ? xhr.statusText || "Upload failed" : detailFromBody(body);
          reject(new ApiError(xhr.status, detail));
        };

        xhr.onerror = () => {
          reject(new ApiError(0, "Network error"));
        };

        xhr.onabort = () => {
          reject(new ApiError(0, "upload cancelled"));
        };

        if (signal) {
          signal.addEventListener("abort", () => xhr.abort(), { once: true });
        }

        xhr.send(form);
      }),
  );
}
