/**
 * All API calls go through here: Authorization bearer on every request, {detail} / FastAPI
 * 422-list bodies mapped to ApiError, and a single silent-renew-then-retry on 401 before
 * giving up and calling onUnauthorized().
 */

export class ApiError extends Error {
  status: number;
  detail: string | unknown;

  constructor(status: number, detail: string | unknown) {
    super(typeof detail === "string" ? detail : `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface ValidationErrorItem {
  loc?: Array<string | number>;
  msg?: string;
}

function isValidationErrorItem(value: unknown): value is ValidationErrorItem {
  return typeof value === "object" && value !== null && ("loc" in value || "msg" in value);
}

/** FastAPI 422 bodies carry a list of {loc, msg}; join as "loc_last: msg; loc_last: msg". */
function formatValidationErrors(items: unknown[]): string {
  return items
    .map((item) => {
      if (!isValidationErrorItem(item)) return String(item);
      const loc = item.loc ?? [];
      const last = loc[loc.length - 1];
      return `${last ?? "error"}: ${item.msg ?? "invalid"}`;
    })
    .join("; ");
}

function detailFromBody(body: unknown): string | unknown {
  if (typeof body !== "object" || body === null || !("detail" in body)) return body;
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return formatValidationErrors(detail);
  return detail;
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  const detail = body === undefined ? response.statusText : detailFromBody(body);
  return new ApiError(response.status, detail);
}

export interface ApiFetchOptions {
  getToken: () => Promise<string>;
}

async function withBearer(
  path: string,
  init: RequestInit | undefined,
  getToken: () => Promise<string>,
): Promise<Response> {
  const token = await getToken();
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(path, { ...init, headers });
}

/** Single-attempt fetch: bearer token in, ApiError out on non-2xx, parsed JSON on success. */
export async function apiFetch<T>(
  path: string,
  init: RequestInit | undefined,
  { getToken }: ApiFetchOptions,
): Promise<T> {
  const response = await withBearer(path, init, getToken);
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function withRenewAndRetry<T>(
  run: () => Promise<T>,
  onUnauthorized: () => void,
  renew?: () => Promise<unknown>,
): Promise<T> {
  try {
    return await run();
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    if (renew) await renew();
    try {
      return await run();
    } catch (retryError) {
      if (retryError instanceof ApiError && retryError.status === 401) onUnauthorized();
      throw retryError;
    }
  }
}

/**
 * Bound API helpers. On a 401: calls renew() if provided, re-reads the token via getToken()
 * (so a caller whose getToken() itself does silent renewal still picks up a fresh token),
 * and retries once. A second 401 calls onUnauthorized() (the caller redirects to login) and
 * rejects with ApiError.
 */
export function createApi(
  getToken: () => Promise<string>,
  onUnauthorized: () => void,
  renew?: () => Promise<unknown>,
) {
  const opts: ApiFetchOptions = { getToken };

  return {
    get: <T>(path: string, init?: RequestInit) =>
      withRenewAndRetry(() => apiFetch<T>(path, { ...init, method: "GET" }, opts), onUnauthorized, renew),

    post: <T>(path: string, body?: unknown, init?: RequestInit) =>
      withRenewAndRetry(
        () =>
          apiFetch<T>(
            path,
            {
              ...init,
              method: "POST",
              headers: { "Content-Type": "application/json", ...init?.headers },
              body: body === undefined ? undefined : JSON.stringify(body),
            },
            opts,
          ),
        onUnauthorized,
        renew,
      ),

    postForm: <T>(path: string, form: FormData, init?: RequestInit) =>
      withRenewAndRetry(
        () => apiFetch<T>(path, { ...init, method: "POST", body: form }, opts),
        onUnauthorized,
        renew,
      ),

    del: <T>(path: string, init?: RequestInit) =>
      withRenewAndRetry(() => apiFetch<T>(path, { ...init, method: "DELETE" }, opts), onUnauthorized, renew),
  };
}

/** Same-origin API paths are already servable as-is (nginx/dev-proxy both mount at /api). */
export function downloadUrl(path: string): string {
  return path;
}

/**
 * Raw Response for streaming/downloads (SSE, file downloads) that can't go through
 * apiFetch's JSON parsing. Same bearer + single renew/retry on 401 as the bound helpers.
 */
export async function authFetch(
  path: string,
  init: RequestInit | undefined,
  getToken: () => Promise<string>,
  renew?: () => Promise<unknown>,
): Promise<Response> {
  let response = await withBearer(path, init, getToken);
  if (response.status === 401) {
    if (renew) await renew();
    response = await withBearer(path, init, getToken);
  }
  return response;
}
